"""Inbound endpoint: Odoo → middleware (reverse flow).

Flow (ADR-0011, ADR-0013):
1. Validate shared secret (constant-time).      <10ms
2. Enqueue arq job (dedup by (model, id)).
3. Return 200 fast (Odoo native webhook timeout ~1s).
All the work happens in the arq worker (fetch from Odoo + push to Saleor).
"""

from __future__ import annotations

import hmac
import time

import structlog
from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from saleor_bridge.config import get_settings

log = structlog.get_logger()
router = APIRouter(tags=["odoo-events"])


class OdooEventPayload(BaseModel):
    odoo_model: str  # "product.template" | "product.category"
    odoo_id: int
    action: str = "write"  # create | write | unlink


@router.post("/odoo-events", response_model=None)
async def receive_odoo_event(
    request: Request,
    secret: str = Query(...),
    payload: OdooEventPayload = Body(...),
) -> JSONResponse | dict:
    settings = get_settings()
    configured = settings.odoo_webhook_secret
    # Refuse to run on an unset / publicly-known secret: a blank secret would match a
    # blank query param, and "changeme-please" ships in source. Fail closed (503) so a
    # misconfigured deploy can't silently accept forged Odoo events.
    if not configured or configured == "changeme-please":
        log.error("odoo_event_secret_not_configured", model=payload.odoo_model, odoo_id=payload.odoo_id)
        return JSONResponse(
            {"ok": False, "error": "webhook secret not configured"}, status_code=503
        )
    if not hmac.compare_digest(secret, configured):
        log.warning("odoo_event_bad_secret", model=payload.odoo_model, odoo_id=payload.odoo_id)
        return JSONResponse({"ok": False, "error": "invalid secret"}, status_code=401)

    pool = request.app.state.arq_pool
    # defer ~3s: base.automation fires INSIDE the Odoo transaction (before commit);
    # give Odoo time to commit so the worker reads the fresh record over JSON-2.
    # _job_id with a 5-sec bucket: collapses bursts (the "two writes in a row" race), but
    # does NOT block later edits (otherwise keep_result=1h would swallow updates).
    # Whichever job survives the bucket still reads the FRESH record from Odoo → sees the latest.
    bucket = int(time.time() // 5)
    job = await pool.enqueue_job(
        "sync_odoo_record_to_saleor",
        payload.odoo_model,
        payload.odoo_id,
        payload.action,
        _job_id=f"odoo:{payload.odoo_model}:{payload.odoo_id}:{bucket}",
        _defer_by=3,
    )
    log.info(
        "odoo_event_queued",
        model=payload.odoo_model, odoo_id=payload.odoo_id, action=payload.action,
        job_id=getattr(job, "job_id", None),
    )
    return {"ok": True, "queued": True, "job_id": getattr(job, "job_id", None)}
