"""POST /api/odoo-events: secret gate (ADR-0011)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from saleor_bridge.api import odoo_events
from saleor_bridge.config import Settings

_SECRET = "s3cret-bridge-token-aaaaaaaaaaaa"


class _FakePool:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def enqueue_job(self, name, *args, _job_id=None, **kw):
        self.calls.append({"name": name, "args": args, "job_id": _job_id})

        class _Job:
            job_id = _job_id

        return _Job()


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.setattr(
        odoo_events, "get_settings", lambda: Settings(odoo_webhook_secret=_SECRET)
    )
    app = FastAPI()
    app.include_router(odoo_events.router, prefix="/api")
    app.state.arq_pool = _FakePool()
    return TestClient(app)


_BODY = {"odoo_model": "product.template", "odoo_id": 7, "action": "write"}


def test_wrong_secret_401(client):
    r = client.post("/api/odoo-events", params={"secret": "nope"}, json=_BODY)
    assert r.status_code == 401
    assert r.json()["ok"] is False
    assert client.app.state.arq_pool.calls == []  # ничего не поставили в очередь


def test_correct_secret_queues(client):
    r = client.post("/api/odoo-events", params={"secret": _SECRET}, json=_BODY)
    assert r.status_code == 200
    assert r.json()["queued"] is True
    calls = client.app.state.arq_pool.calls
    assert len(calls) == 1
    assert calls[0]["name"] == "sync_odoo_record_to_saleor"
    assert calls[0]["args"] == ("product.template", 7, "write")


def test_missing_secret_422(client):
    # secret — обязательный query param.
    r = client.post("/api/odoo-events", json=_BODY)
    assert r.status_code == 422


def _client_with_secret(monkeypatch, secret: str) -> TestClient:
    monkeypatch.setattr(
        odoo_events, "get_settings", lambda: Settings(odoo_webhook_secret=secret)
    )
    app = FastAPI()
    app.include_router(odoo_events.router, prefix="/api")
    app.state.arq_pool = _FakePool()
    return TestClient(app)


def test_unconfigured_secret_503(monkeypatch):
    # Empty secret → endpoint fails closed (would otherwise match a blank query param).
    c = _client_with_secret(monkeypatch, "")
    r = c.post("/api/odoo-events", params={"secret": ""}, json=_BODY)
    assert r.status_code == 503
    assert c.app.state.arq_pool.calls == []


def test_legacy_default_secret_503(monkeypatch):
    # The old in-source default is publicly known → refuse it even if a deploy still ships it.
    c = _client_with_secret(monkeypatch, "changeme-please")
    r = c.post("/api/odoo-events", params={"secret": "changeme-please"}, json=_BODY)
    assert r.status_code == 503
    assert c.app.state.arq_pool.calls == []
