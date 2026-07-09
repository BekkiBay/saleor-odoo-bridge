"""JWS signature verification for Saleor webhooks.

Reference:
- https://docs.saleor.io/developer/extending/webhooks/payload-signature
- https://github.com/saleor/saleor/discussions/9822

Saleor 3.5+ signs the payload via a detached JWS (RS256). The `Saleor-Signature`
header contains a compact JWS with an empty middle part — the actual body is sent
separately.

Verify algorithm:
1. Fetch JWKS from {saleor_url}/.well-known/jwks.json (1 hour cache).
2. Extract header.kid from the JWS, find the matching JWK.
3. Reconstruct the detached JWS: `<protected_header>.<base64(body)>.<signature>`.
4. Verify via joserfc.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass

import httpx
import structlog
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers

log = structlog.get_logger()

_JWKS_CACHE: dict[str, tuple[float, dict]] = {}
_JWKS_TTL_SECONDS = 3600


def _b64url_no_pad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _jwks_url_for(saleor_api_url: str) -> str:
    """Saleor server hosts JWKS at the domain root.

    A Saleor API endpoint like https://shop.example.com/graphql/ has its JWKS at
    https://shop.example.com/.well-known/jwks.json. Strip the path.
    """
    from urllib.parse import urlparse

    p = urlparse(saleor_api_url)
    return f"{p.scheme}://{p.netloc}/.well-known/jwks.json"


async def fetch_jwks(saleor_api_url: str, *, force_refresh: bool = False) -> dict:
    """Fetch the JWKS, 1 hour cache."""
    url = _jwks_url_for(saleor_api_url)
    now = time.time()
    cached = _JWKS_CACHE.get(url)
    if cached and not force_refresh:
        ts, data = cached
        if now - ts < _JWKS_TTL_SECONDS:
            return data

    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.get(url)
        r.raise_for_status()
        data = r.json()

    _JWKS_CACHE[url] = (now, data)
    return data


@dataclass
class VerifyResult:
    valid: bool
    reason: str = ""
    kid: str = ""


def _b64url_uint(val: str) -> int:
    padded = val + "=" * (-len(val) % 4)
    return int.from_bytes(base64.urlsafe_b64decode(padded), "big")


def _rsa_public_key(jwk_dict: dict):
    """Cryptography RSAPublicKey from JWK (n, e)."""
    return RSAPublicNumbers(
        e=_b64url_uint(jwk_dict["e"]),
        n=_b64url_uint(jwk_dict["n"]),
    ).public_key()


def verify_detached_jws(
    raw_body: bytes,
    saleor_signature_header: str,
    jwks_data: dict,
) -> VerifyResult:
    """Verify a Saleor detached JWS signature (RS256).

    `saleor_signature_header` has the form `<protected>..<signature>` (detached:
    the middle part is empty, the payload is sent separately as the HTTP body).

    Saleor signs per RFC 7797 with `b64:false` (crit=["b64"]) — the signing input
    is `<protected>.<RAW body>` (the payload is NOT base64-encoded). We support both
    b64 variants in case Saleor's behavior changes.
    """
    parts = saleor_signature_header.split(".")
    if len(parts) != 3:
        return VerifyResult(False, f"signature header must have 3 parts, got {len(parts)}")
    protected, _empty, signature = parts
    if _empty:
        # Saleor sends this with an empty payload (detached). If it's not empty, this
        # isn't a detached JWS — reject it.
        return VerifyResult(False, "expected detached JWS (empty middle part)")

    try:
        header = json.loads(base64.urlsafe_b64decode(protected + "=="))
    except Exception as e:  # noqa: BLE001
        return VerifyResult(False, f"cannot parse protected header: {e}")
    kid = header.get("kid", "")
    payload_encoded = header.get("b64", True)  # RFC 7797: b64=false → raw payload

    # Find matching JWK.
    matching = [k for k in jwks_data.get("keys", []) if k.get("kid") == kid]
    if not matching:
        return VerifyResult(False, f"no JWK with kid={kid!r} in JWKS", kid=kid)

    # Signing input = ASCII(protected) + "." + payload (raw when b64:false).
    payload_segment = _b64url_no_pad(raw_body).encode("ascii") if payload_encoded else raw_body
    signing_input = protected.encode("ascii") + b"." + payload_segment

    try:
        sig_bytes = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
    except Exception as e:  # noqa: BLE001
        return VerifyResult(False, f"cannot decode signature: {e}", kid=kid)

    try:
        _rsa_public_key(matching[0]).verify(
            sig_bytes, signing_input, padding.PKCS1v15(), hashes.SHA256()
        )
    except InvalidSignature:
        return VerifyResult(False, "signature verification failed: bad_signature", kid=kid)
    except Exception as e:  # noqa: BLE001
        return VerifyResult(False, f"signature verification failed: {e}", kid=kid)

    return VerifyResult(True, "ok", kid=kid)
