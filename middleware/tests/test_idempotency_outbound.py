"""Outbound dedup: повторный webhook для (model, id) → стабильный arq _job_id.

Дедуп самой джобы — ответственность arq (одинаковый _job_id), мы проверяем что
API даёт детерминированный job_id, по которому arq схлопнет дубли.
"""

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


def test_same_record_same_job_id_within_burst(client):
    body = {"odoo_model": "product.template", "odoo_id": 7, "action": "write"}
    client.post("/api/odoo-events", params={"secret": _SECRET}, json=body)
    client.post("/api/odoo-events", params={"secret": _SECRET}, json=body)
    calls = client.app.state.arq_pool.calls
    assert len(calls) == 2
    # одинаковый bucketed job_id → arq схлопнет дубли в один
    assert calls[0]["job_id"] == calls[1]["job_id"]
    assert calls[0]["job_id"].startswith("odoo:product.template:7:")


def test_different_records_distinct_job_ids(client):
    client.post("/api/odoo-events", params={"secret": _SECRET},
                json={"odoo_model": "product.template", "odoo_id": 7, "action": "write"})
    client.post("/api/odoo-events", params={"secret": _SECRET},
                json={"odoo_model": "product.category", "odoo_id": 4, "action": "create"})
    jobs = [c["job_id"] for c in client.app.state.arq_pool.calls]
    assert jobs[0].startswith("odoo:product.template:7:")
    assert jobs[1].startswith("odoo:product.category:4:")
    assert jobs[0] != jobs[1]
