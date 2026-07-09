"""Shared fixtures for unit tests."""

from __future__ import annotations

import base64
import json

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

_KID = "test-key-001"


def _b64url_no_pad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _uint_b64(n: int) -> str:
    return _b64url_no_pad(n.to_bytes((n.bit_length() + 7) // 8, "big"))


@pytest.fixture(scope="session")
def rsa_keypair() -> tuple[rsa.RSAPrivateKey, dict]:
    """RSA private key + a matching JWKS (Saleor's format)."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = private_key.public_key().public_numbers()
    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "alg": "RS256",
                "use": "sig",
                "kid": _KID,
                "n": _uint_b64(pub.n),
                "e": _uint_b64(pub.e),
            }
        ]
    }
    return private_key, jwks


@pytest.fixture
def sign_payload(rsa_keypair):
    """Returns (raw_body) -> a Saleor-style detached JWS header `<protected>..<sig>`.

    Reproduces Saleor's format EXACTLY: RFC 7797 with `b64:false` (crit=["b64"]),
    signing input = `<protected>.<RAW body>` (payload NOT base64), and the JWS
    payload itself is empty (detached). This is what actually arrives in Saleor-Signature.
    """
    private_key, _ = rsa_keypair

    def _sign(raw_body: bytes) -> str:
        header = {"alg": "RS256", "b64": False, "crit": ["b64"], "kid": _KID, "typ": "JWT"}
        protected = _b64url_no_pad(json.dumps(header, separators=(",", ":")).encode())
        signing_input = protected.encode("ascii") + b"." + raw_body
        sig = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        return f"{protected}..{_b64url_no_pad(sig)}"

    return _sign
