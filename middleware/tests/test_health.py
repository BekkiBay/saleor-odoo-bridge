"""Liveness vs readiness semantics.

/health must stay 200 so a degraded container is still observable; /ready must
return 503 so orchestrators stop routing traffic to a bridge that cannot
enqueue or deliver a single event.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from saleor_bridge.api import health as health_api


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(health_api.router)
    return TestClient(app, raise_server_exceptions=False)


def _patch_deps(monkeypatch: pytest.MonkeyPatch, *, redis_ok: bool, odoo_ok: bool) -> None:
    async def fake_redis(_settings) -> bool:
        return redis_ok

    async def fake_odoo(_settings) -> bool:
        return odoo_ok

    monkeypatch.setattr(health_api, "_redis_ok", fake_redis)
    monkeypatch.setattr(health_api, "_odoo_ok", fake_odoo)


def test_ready_returns_200_when_all_deps_up(client, monkeypatch):
    _patch_deps(monkeypatch, redis_ok=True, odoo_ok=True)
    r = client.get("/ready")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"


@pytest.mark.parametrize(
    ("redis_ok", "odoo_ok"),
    [(False, True), (True, False), (False, False)],
)
def test_ready_returns_503_when_any_dep_down(client, monkeypatch, redis_ok, odoo_ok):
    _patch_deps(monkeypatch, redis_ok=redis_ok, odoo_ok=odoo_ok)
    r = client.get("/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    assert body["redis"] is redis_ok
    assert body["odoo"] is odoo_ok


def test_health_stays_200_even_when_deps_down(client, monkeypatch):
    _patch_deps(monkeypatch, redis_ok=False, odoo_ok=False)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "redis": "fail", "odoo": "fail"}
