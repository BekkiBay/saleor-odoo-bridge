"""Webhook receiver endpoints.

Flow per ADR / spec:
1. JWS verify (<50ms).
2. Idempotency check (Redis SET NX, 24h TTL).
3. Enqueue arq job.
4. Return 200 (<200ms total).
No business logic inline — it all happens in the arq worker.
"""

from __future__ import annotations

import json
import time
import uuid

import structlog
from fastapi import APIRouter, Header, Request, Response

from saleor_bridge.config import get_settings
from saleor_bridge.queue.idempotency import already_processed, make_key, release
from saleor_bridge.saleor.signature import fetch_jwks, verify_detached_jws

log = structlog.get_logger()
router = APIRouter(tags=["webhooks"])


async def _verify(raw_body: bytes, sig: str | None, api_url: str) -> tuple[bool, str]:
    if not sig:
        return False, "missing Saleor-Signature header"
    try:
        jwks = await fetch_jwks(api_url)
    except Exception as e:  # noqa: BLE001
        return False, f"jwks fetch failed: {e}"
    res = verify_detached_jws(raw_body, sig, jwks)
    if not res.valid:
        try:
            jwks = await fetch_jwks(api_url, force_refresh=True)
            res = verify_detached_jws(raw_body, sig, jwks)
        except Exception as e:  # noqa: BLE001
            return False, f"jwks refresh failed: {e}"
    return res.valid, res.reason if not res.valid else res.kid


def _extract_saleor_id(payload: dict) -> str:
    """Best-effort extraction of the saleor id for the idempotency key."""
    data = payload.get("event", payload)
    for k in ("order", "user"):
        if isinstance(data.get(k), dict) and data[k].get("id"):
            return data[k]["id"]
    return data.get("id", "")


async def _handle(
    request: Request,
    response: Response,
    *,
    event_name: str,
    arq_task: str,
    saleor_signature: str | None,
    saleor_event: str | None,
    saleor_api_url: str | None,
    saleor_domain: str | None,
) -> dict:
    trace_id = str(uuid.uuid4())
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(trace_id=trace_id, evt=event_name)
    started = time.monotonic()
    settings = get_settings()

    raw = await request.body()

    # We fetch JWKS from the configured Saleor URL (settings.saleor_api_url), NOT from
    # the saleor-api-url in the webhook header: (1) the header may be unreachable from
    # the container (Saleor announces localhost), (2) trusting the signing-key source
    # from the request itself is unsafe. In single-tenant prod it's the same URL anyway.
    valid, info = await _verify(raw, saleor_signature, settings.saleor_api_url)
    if not valid:
        log.warning("webhook_signature_invalid", reason=info, domain=saleor_domain)
        response.status_code = 401
        return {"ok": False, "reason": info}

    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        payload = {}

    saleor_id = _extract_saleor_id(payload)

    # Idempotency
    redis_client = request.app.state.redis
    idem_key = make_key(event_name, saleor_id, {"event": saleor_event})
    if await already_processed(redis_client, idem_key):
        log.info("webhook_duplicate_skipped", saleor_id=saleor_id)
        return {"ok": True, "duplicate": True, "trace_id": trace_id}

    # Enqueue. We already CLAIMED the idempotency key above; if enqueue raises we must
    # release it, otherwise the 24h TTL drops this event permanently and Saleor's retry
    # is silently skipped as a 'duplicate'. Release + re-raise → 500 → Saleor retries.
    pool = request.app.state.arq_pool
    try:
        job = await pool.enqueue_job(arq_task, payload)
    except Exception:
        await release(redis_client, idem_key)
        raise
    took = int((time.monotonic() - started) * 1000)
    log.info(
        "webhook_received",
        signature_valid=True, kid=info, saleor_id=saleor_id,
        job_id=getattr(job, "job_id", None), took_ms=took,
    )
    return {"ok": True, "trace_id": trace_id, "job_id": getattr(job, "job_id", None)}


# ── customers ──────────────────────────────────────────────────────────────

@router.post("/customer-created")
async def customer_created(
    request: Request, response: Response,
    saleor_signature: str | None = Header(None, alias="saleor-signature"),
    saleor_event: str | None = Header(None, alias="saleor-event"),
    saleor_api_url: str | None = Header(None, alias="saleor-api-url"),
    saleor_domain: str | None = Header(None, alias="saleor-domain"),
) -> dict:
    return await _handle(
        request, response, event_name="CUSTOMER_CREATED",
        arq_task="process_customer_created",
        saleor_signature=saleor_signature, saleor_event=saleor_event,
        saleor_api_url=saleor_api_url, saleor_domain=saleor_domain,
    )


@router.post("/customer-updated")
async def customer_updated(
    request: Request, response: Response,
    saleor_signature: str | None = Header(None, alias="saleor-signature"),
    saleor_event: str | None = Header(None, alias="saleor-event"),
    saleor_api_url: str | None = Header(None, alias="saleor-api-url"),
    saleor_domain: str | None = Header(None, alias="saleor-domain"),
) -> dict:
    return await _handle(
        request, response, event_name="CUSTOMER_UPDATED",
        arq_task="process_customer_updated",
        saleor_signature=saleor_signature, saleor_event=saleor_event,
        saleor_api_url=saleor_api_url, saleor_domain=saleor_domain,
    )


# ── orders ─────────────────────────────────────────────────────────────────

@router.post("/order-created")
async def order_created(
    request: Request, response: Response,
    saleor_signature: str | None = Header(None, alias="saleor-signature"),
    saleor_event: str | None = Header(None, alias="saleor-event"),
    saleor_api_url: str | None = Header(None, alias="saleor-api-url"),
    saleor_domain: str | None = Header(None, alias="saleor-domain"),
) -> dict:
    return await _handle(
        request, response, event_name="ORDER_CREATED",
        arq_task="process_order_created",
        saleor_signature=saleor_signature, saleor_event=saleor_event,
        saleor_api_url=saleor_api_url, saleor_domain=saleor_domain,
    )


@router.post("/order-confirmed")
async def order_confirmed(
    request: Request, response: Response,
    saleor_signature: str | None = Header(None, alias="saleor-signature"),
    saleor_event: str | None = Header(None, alias="saleor-event"),
    saleor_api_url: str | None = Header(None, alias="saleor-api-url"),
    saleor_domain: str | None = Header(None, alias="saleor-domain"),
) -> dict:
    # ADR-0005: ORDER_CONFIRMED → NO business logic (we wait for PAID). But JWS
    # verification still has to run, same as on the other webhooks — otherwise any
    # unauthenticated call gets 200 and bypasses the auth gate. Verify → noop (no enqueue).
    settings = get_settings()
    raw = await request.body()
    valid, info = await _verify(raw, saleor_signature, settings.saleor_api_url)
    if not valid:
        log.warning("webhook_signature_invalid", reason=info, evt="ORDER_CONFIRMED", domain=saleor_domain)
        response.status_code = 401
        return {"ok": False, "reason": info}
    trace_id = str(uuid.uuid4())
    log.info("order_confirmed_noop", trace_id=trace_id)
    return {"ok": True, "noop": True, "trace_id": trace_id}


@router.post("/order-fully-paid")
async def order_fully_paid(
    request: Request, response: Response,
    saleor_signature: str | None = Header(None, alias="saleor-signature"),
    saleor_event: str | None = Header(None, alias="saleor-event"),
    saleor_api_url: str | None = Header(None, alias="saleor-api-url"),
    saleor_domain: str | None = Header(None, alias="saleor-domain"),
) -> dict:
    return await _handle(
        request, response, event_name="ORDER_FULLY_PAID",
        arq_task="process_order_paid",
        saleor_signature=saleor_signature, saleor_event=saleor_event,
        saleor_api_url=saleor_api_url, saleor_domain=saleor_domain,
    )


@router.post("/order-cancelled")
async def order_cancelled(
    request: Request, response: Response,
    saleor_signature: str | None = Header(None, alias="saleor-signature"),
    saleor_event: str | None = Header(None, alias="saleor-event"),
    saleor_api_url: str | None = Header(None, alias="saleor-api-url"),
    saleor_domain: str | None = Header(None, alias="saleor-domain"),
) -> dict:
    return await _handle(
        request, response, event_name="ORDER_CANCELLED",
        arq_task="process_order_cancelled",
        saleor_signature=saleor_signature, saleor_event=saleor_event,
        saleor_api_url=saleor_api_url, saleor_domain=saleor_domain,
    )
