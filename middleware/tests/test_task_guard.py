"""_guard: a usecase ok=False must surface as a failure (retry + final alert),
not be returned as a value that arq treats as a successful job."""

from __future__ import annotations

import pytest
from arq.worker import Retry

from saleor_bridge.queue import tasks
from saleor_bridge.queue.tasks import SyncFailed, _guard


@pytest.mark.asyncio
async def test_guard_ok_true_passthrough():
    async def fn() -> dict:
        return {"ok": True, "odoo_id": 5}

    res = await _guard(
        {"job_try": 1, "max_tries": 3},
        event="ORDER_CREATED", model_name="sale.order", saleor_id="1", fn=fn,
    )
    assert res == {"ok": True, "odoo_id": 5}


@pytest.mark.asyncio
async def test_guard_ok_false_retries_before_final():
    async def fn() -> dict:
        return {"ok": False, "message": "no stock.warehouse in Odoo"}

    with pytest.raises(Retry):  # job_try < max_tries → arq re-queues with backoff
        await _guard(
            {"job_try": 1, "max_tries": 3},
            event="ODOO_WRITE", model_name="product.template", saleor_id="7", fn=fn,
        )


@pytest.mark.asyncio
async def test_guard_ok_false_final_try_alerts(monkeypatch):
    captured: dict = {}

    async def fake_final(ctx, event, model_name, saleor_id, exc, *, outbound=False):
        captured["exc"] = exc

    monkeypatch.setattr(tasks, "_on_final_failure", fake_final)

    async def fn() -> dict:
        return {"ok": False, "message": "customer sync failed"}

    with pytest.raises(SyncFailed):  # last try → permanent failure propagates
        await _guard(
            {"job_try": 3, "max_tries": 3},
            event="ORDER_CREATED", model_name="sale.order", saleor_id="1", fn=fn,
        )
    assert isinstance(captured["exc"], SyncFailed)
