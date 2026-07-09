"""JWS signature verification для Saleor webhooks.

Reference:
- https://docs.saleor.io/developer/extending/webhooks/payload-signature
- https://github.com/saleor/saleor/discussions/9822

Saleor 3.5+ подписывает payload через detached JWS (RS256). Header `Saleor-Signature`
содержит компактный JWS с пустым telom — реальный body передаётся отдельно.

Алгоритм verify:
1. Fetch JWKS из {saleor_url}/.well-known/jwks.json (кэш 1 час).
2. Извлечь header.kid из JWS, найти соответствующий JWK.
3. Восстановить detached JWS: `<protected_header>.<base64(body)>.<signature>`.
4. Verify через joserfc.
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
    """Saleor server hosts JWKS на корне домена.

    Saleor API endpoint типа https://shop.example.com/graphql/ — JWKS лежит на
    https://shop.example.com/.well-known/jwks.json. Стрипаем path.
    """
    from urllib.parse import urlparse

    p = urlparse(saleor_api_url)
    return f"{p.scheme}://{p.netloc}/.well-known/jwks.json"


async def fetch_jwks(saleor_api_url: str, *, force_refresh: bool = False) -> dict:
    """Получить JWKS, кэш 1 час."""
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
    """Cryptography RSAPublicKey из JWK (n, e)."""
    return RSAPublicNumbers(
        e=_b64url_uint(jwk_dict["e"]),
        n=_b64url_uint(jwk_dict["n"]),
    ).public_key()


def verify_detached_jws(
    raw_body: bytes,
    saleor_signature_header: str,
    jwks_data: dict,
) -> VerifyResult:
    """Verify Saleor detached JWS подпись (RS256).

    `saleor_signature_header` имеет вид `<protected>..<signature>` (detached:
    middle часть — пустая, payload передаётся отдельно как HTTP body).

    Saleor подписывает по RFC 7797 с `b64:false` (crit=["b64"]) — signing input
    это `<protected>.<RAW body>` (payload НЕ base64-кодируется). Поддерживаем оба
    варианта b64 на случай изменения поведения Saleor.
    """
    parts = saleor_signature_header.split(".")
    if len(parts) != 3:
        return VerifyResult(False, f"signature header must have 3 parts, got {len(parts)}")
    protected, _empty, signature = parts
    if _empty:
        # Saleor отправляет с пустым payload (detached). Если не пусто — это
        # не detached JWS, отказываем.
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

    # Signing input = ASCII(protected) + "." + payload (raw при b64:false).
    if payload_encoded:
        payload_segment = _b64url_no_pad(raw_body).encode("ascii")
    else:
        payload_segment = raw_body
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
