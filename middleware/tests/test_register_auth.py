"""POST /api/register auth gate: only persist a token Saleor genuinely issued.

Without verification any reachable POST could overwrite the stored Saleor app token
(break sync or inject a rogue token). We mock the Saleor-side verification here; the
real check runs `query { app { id } }` against the configured Saleor with the token."""

from __future__ import annotations

from typing import ClassVar

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from saleor_bridge.api import register
from saleor_bridge.config import Settings, get_settings


class _FakeAPL:
    """Captures the AuthData the endpoint would persist."""

    saved: ClassVar[list] = []

    def __init__(self, url: str) -> None:
        pass

    async def set(self, auth) -> None:
        _FakeAPL.saved.append(auth)

    async def aclose(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _reset() -> None:
    _FakeAPL.saved = []


def _client(monkeypatch, *, token_valid: bool) -> TestClient:
    async def fake_verify(api_url: str, token: str) -> bool:
        return token_valid

    monkeypatch.setattr(register, "_verify_app_token", fake_verify)
    monkeypatch.setattr(register, "RedisAPL", _FakeAPL)

    app = FastAPI()
    app.include_router(register.router, prefix="/api")
    app.dependency_overrides[get_settings] = lambda: Settings(
        saleor_api_url="http://saleor/graphql/", redis_url="redis://x:6379/0"
    )
    return TestClient(app)


def test_valid_token_persisted(monkeypatch):
    c = _client(monkeypatch, token_valid=True)
    r = c.post("/api/register", json={"auth_token": "real-app-token", "app_id": "QXBwOjE="})
    assert r.status_code == 200
    assert r.json() == {"success": True}
    assert len(_FakeAPL.saved) == 1
    assert _FakeAPL.saved[0].token == "real-app-token"


def test_invalid_token_rejected(monkeypatch):
    c = _client(monkeypatch, token_valid=False)
    r = c.post("/api/register", json={"auth_token": "forged"})
    assert r.status_code == 401
    assert r.json()["success"] is False
    assert _FakeAPL.saved == []  # nothing persisted


def test_missing_token(monkeypatch):
    c = _client(monkeypatch, token_valid=True)
    r = c.post("/api/register", json={})
    assert r.json() == {"success": False, "error": "missing auth_token"}
    assert _FakeAPL.saved == []  # never even attempted verification/persist
