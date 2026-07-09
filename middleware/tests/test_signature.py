"""Unit tests for JWS signature verification."""

from __future__ import annotations

from saleor_bridge.saleor.signature import verify_detached_jws


def test_verify_happy_path(rsa_keypair, sign_payload):
    """A payload signed with our key verifies successfully."""
    _, jwks = rsa_keypair
    body = b'{"hello": "world"}'
    sig = sign_payload(body)

    result = verify_detached_jws(body, sig, jwks)
    assert result.valid, result.reason
    assert result.kid == "test-key-001"


def test_verify_fails_on_tampered_body(rsa_keypair, sign_payload):
    """If the body is modified after signing — verify fails."""
    _, jwks = rsa_keypair
    body = b'{"hello": "world"}'
    sig = sign_payload(body)

    tampered = b'{"hello": "evil"}'
    result = verify_detached_jws(tampered, sig, jwks)
    assert not result.valid


def test_verify_fails_on_unknown_kid(rsa_keypair, sign_payload):
    """If JWKS has no key with the matching kid — verify fails."""
    body = b"test"
    sig = sign_payload(body)
    empty_jwks = {"keys": []}

    result = verify_detached_jws(body, sig, empty_jwks)
    assert not result.valid
    assert "kid" in result.reason or "JWK" in result.reason


def test_verify_fails_on_malformed_signature(rsa_keypair):
    """Header not in <a>..<b> format → fail."""
    _, jwks = rsa_keypair
    body = b"test"

    result = verify_detached_jws(body, "not-a-valid-jws", jwks)
    assert not result.valid
    assert "3 parts" in result.reason


def test_verify_fails_on_non_detached(rsa_keypair):
    """Header of the form <a>.<b>.<c> (without an empty middle) — reject."""
    _, jwks = rsa_keypair
    body = b"test"

    result = verify_detached_jws(body, "header.payload.signature", jwks)
    assert not result.valid
    assert "detached" in result.reason
