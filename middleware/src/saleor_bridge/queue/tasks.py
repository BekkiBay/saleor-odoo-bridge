"""arq task functions. Map raw payload → domain → usecase.

Each task:
1. Parse payload via saleor adapters → domain model.
2. Call usecase (sync_customer / sync_order).
3. On error → raise (arq retries, max_tries in WorkerSettings).
4. On final try fail → alert (Slack + email) + mark saleor.binding failed (ADR-0008).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from arq.worker import Retry

from saleor_bridge.adapters.odoo.binding import BindingRepository
from saleor_bridge.adapters.saleor.catalog_admin import resolve_channel
from saleor_bridge.adapters.saleor.customer_mapper import (
    extract_user,
    saleor_user_to_customer,
)
from saleor_bridge.adapters.saleor.factory import get_saleor_client
from saleor_bridge.adapters.saleor.order_mapper import extract_order, saleor_order_to_order
from saleor_bridge.adapters.saleor.product_type_mutations import ensure_product_type
from saleor_bridge.domain.enums import OrderStatus
from saleor_bridge.observability.email import send_email_alert
from saleor_bridge.observability.slack import send_slack_alert
from saleor_bridge.odoo.client import OdooClient
from saleor_bridge.usecases.reconcile_stocks import run_reconcile_stocks
from saleor_bridge.usecases.sync_attribute_to_saleor import sync_attribute_to_saleor
from saleor_bridge.usecases.sync_canonical_status_to_saleor import (
    sync_canonical_status_to_saleor,
)
from saleor_bridge.usecases.sync_category_to_saleor import sync_category_to_saleor
from saleor_bridge.usecases.sync_customer import sync_customer_to_odoo
from saleor_bridge.usecases.sync_order import sync_order_to_odoo
from saleor_bridge.usecases.sync_order_status_to_saleor import (
    sync_order_state_to_saleor,
    sync_picking_to_saleor,
)
from saleor_bridge.usecases.sync_product_to_saleor import sync_product_to_saleor
from saleor_bridge.usecases.sync_stock_to_saleor import sync_stock_to_saleor
from saleor_bridge.usecases.sync_template_variants_to_saleor import (
    sync_template_variants_to_saleor,
)
from saleor_bridge.usecases.sync_variant_to_saleor import sync_variant_to_saleor

log = structlog.get_logger()


class SyncFailed(RuntimeError):
    """A usecase reported ok=False (real failure) without raising. We convert it to
    an exception so it flows through the same retry+alert path as any other error —
    previously the worker returned it as a normal value and arq marked the job
    successful, so a missing warehouse / unresolved record / customer-sync failure
    was silently dropped with no retry and no alert."""


def _odoo(ctx: dict) -> OdooClient:
    s = ctx["settings"]
    return OdooClient(url=s.odoo_url, db=s.odoo_db, api_key=s.odoo_api_key)


async def _guard(
    ctx: dict,
    *,
    event: str,
    model_name: str,
    saleor_id: str,
    fn: Callable[[], Awaitable[dict]],
    outbound: bool = False,
) -> dict:
    """Run fn; retry with backoff via arq.Retry; on the final attempt → alert + mark failed."""
    try:
        result = await fn()
        if isinstance(result, dict) and result.get("ok") is False:
            raise SyncFailed(str(result.get("message") or "usecase returned ok=False"))
        return result
    except Retry:
        raise  # arq control-flow, leave as-is
    except Exception as exc:
        job_try = ctx.get("job_try", 1)
        max_tries = ctx.get("max_tries", 3)
        log.warning("task_failed", evt=event, saleor_id=saleor_id, try_=job_try, error=str(exc))
        if job_try >= max_tries:
            await _on_final_failure(ctx, event, model_name, saleor_id, exc, outbound=outbound)
            raise  # permanent failure
        # backoff 1s, 4s, 16s ... = 4 ** (job_try - 1)
        raise Retry(defer=4 ** (job_try - 1)) from exc


async def _on_final_failure(
    ctx: dict, event: str, model_name: str, saleor_id: str, exc: Exception, *, outbound: bool = False
) -> None:
    s = ctx["settings"]
    msg = f":rotating_light: saleor-bridge sync FAILED\nevent={event} model={model_name} ref={saleor_id}\nerror={exc}"
    # mark binding failed
    try:
        repo = BindingRepository(_odoo(ctx))
        if outbound:
            await repo.mark_failed_out(model_name, int(saleor_id), str(exc))
        else:
            await repo.mark_failed(model_name, saleor_id, str(exc))
    except Exception as e:  # noqa: BLE001
        log.warning("mark_failed_errored", error=str(e))
    # alerts (optional)
    await send_slack_alert(s.slack_webhook_url, msg)
    send_email_alert(
        ops_email=s.ops_email,
        subject=f"[saleor-bridge] {event} failed for {saleor_id}",
        body=msg,
        smtp_host=s.smtp_host,
        smtp_port=s.smtp_port,
        smtp_user=s.smtp_user,
        smtp_password=s.smtp_password,
        from_addr=s.alert_from_email,
    )
    log.error("task_final_failure", evt=event, saleor_id=saleor_id, error=str(exc))


# ── customer tasks ────────────────────────────────────────────────────────

async def process_customer_created(ctx: dict, payload: dict[str, Any]) -> dict:
    user = extract_user(payload)

    async def _run() -> dict:
        customer = saleor_user_to_customer(user)
        odoo = _odoo(ctx)
        res = await sync_customer_to_odoo(customer, odoo, BindingRepository(odoo))
        return {"ok": res.ok, "odoo_id": res.odoo_id}

    return await _guard(
        ctx, event="CUSTOMER_CREATED", model_name="res.partner", saleor_id=user.id, fn=_run
    )


async def process_customer_updated(ctx: dict, payload: dict[str, Any]) -> dict:
    user = extract_user(payload)

    async def _run() -> dict:
        customer = saleor_user_to_customer(user)
        odoo = _odoo(ctx)
        res = await sync_customer_to_odoo(customer, odoo, BindingRepository(odoo))
        return {"ok": res.ok, "odoo_id": res.odoo_id}

    return await _guard(
        ctx, event="CUSTOMER_UPDATED", model_name="res.partner", saleor_id=user.id, fn=_run
    )


# ── order tasks ───────────────────────────────────────────────────────────

async def _process_order(ctx: dict, payload: dict[str, Any], status: OrderStatus, event: str) -> dict:
    so = extract_order(payload)

    async def _run() -> dict:
        order = saleor_order_to_order(so, status=status)
        odoo = _odoo(ctx)
        res = await sync_order_to_odoo(order, odoo, BindingRepository(odoo))
        return {"ok": res.ok, "odoo_id": res.odoo_id, "warnings": res.warnings}

    return await _guard(ctx, event=event, model_name="sale.order", saleor_id=so.id, fn=_run)


# ── reverse flow: Odoo → Saleor catalog ────────────────────────────────────

async def sync_odoo_record_to_saleor(ctx: dict, model: str, odoo_id: int, action: str) -> dict:
    """Pop Odoo event → fetch record → push to Saleor (product / category)."""
    s = ctx["settings"]

    async def _run() -> dict:
        client = await get_saleor_client(s)
        odoo = _odoo(ctx)
        binding_repo = BindingRepository(odoo)
        if model == "product.category":
            res = await sync_category_to_saleor(odoo_id, client, odoo, binding_repo, redis_url=s.redis_url)
        elif model in ("product.attribute", "product.attribute.value"):
            # ADR-0023/0027: global Attribute + values + assign to ProductType.
            ptype = await ensure_product_type(client, binding_repo, s.saleor_product_type_name)
            res = await sync_attribute_to_saleor(
                odoo_id, client, odoo, binding_repo, product_type_id=ptype, model=model
            )
        elif model == "product.template":
            channel = await resolve_channel(client, s.saleor_default_channel)
            ptype = await ensure_product_type(client, binding_repo, s.saleor_product_type_name)
            res = await sync_product_to_saleor(
                odoo_id, client, odoo, binding_repo,
                channel_id=channel["id"], product_type_id=ptype, redis_url=s.redis_url,
            )
            # Reconcile the variant set (multi-variant + dummy migration).
            if res.ok:
                await sync_template_variants_to_saleor(
                    odoo_id, client, odoo, binding_repo, channel_id=channel["id"]
                )
        elif model == "product.product":
            # A single event fires for product.product from TWO triggers (variant fields
            # AND stock.quant, ADR-0017) — the dedup bucket has no action, so the handler does both.
            # First ensure the variant (price/attrs), then stock per variant.
            channel = await resolve_channel(client, s.saleor_default_channel)
            res = await sync_variant_to_saleor(
                odoo_id, client, odoo, binding_repo, channel_id=channel["id"]
            )
            if res.ok and res.odoo_id is not None:  # odoo_id=None → variant archived, stock not needed
                await sync_stock_to_saleor(
                    odoo_id, client, odoo, binding_repo, safety_buffer=s.stock_safety_buffer
                )
        elif model == "sale.order":
            # Order state change (ADR-0019): worker re-reads state → confirm/cancel.
            res = await sync_order_state_to_saleor(odoo_id, client, odoo, binding_repo)
            # Unified status (spec 2026-06-22): push canonical fulfillment_status metadata
            # in the SAME job (avoids the /odoo-events per-(model,id) dedup collision).
            await sync_canonical_status_to_saleor(odoo_id, client, odoo, binding_repo)
        elif model == "stock.picking":
            # Picking validated (ADR-0019/0021): fulfill the linked Saleor order.
            res = await sync_picking_to_saleor(odoo_id, client, odoo, binding_repo)
            # Unified status (spec 2026-06-22): push canonical fulfillment_status for the
            # linked order (now SHIPPED). res.odoo_id carries the sale.order id.
            if res.ok and res.odoo_id:
                await sync_canonical_status_to_saleor(res.odoo_id, client, odoo, binding_repo)
        else:
            log.info("odoo_event_ignored_model", model=model, odoo_id=odoo_id)
            return {"ok": True, "ignored": model}
        return {"ok": res.ok, "odoo_id": res.odoo_id, "message": res.message}

    return await _guard(
        ctx, event=f"ODOO_{action.upper()}", model_name=model,
        saleor_id=str(odoo_id), fn=_run, outbound=True,
    )


# ── scheduled: stock reconcile (ADR-0018, arq cron daily 02:00 UTC) ───────

async def reconcile_stock_drift(ctx: dict) -> dict:
    """Daily dry-run reconcile: logs drift, WITHOUT auto-fixing (ADR-0018).

    Auto-fix is available only manually via the CLI `reconcile-stocks --apply`.
    """
    s = ctx["settings"]
    res = await run_reconcile_stocks(s, apply=False)
    log.info("stock_reconcile_drift", count=res["drift"], checked=res["checked"], ok=res["ok"])
    return {"drift": res["drift"], "checked": res["checked"]}


async def process_order_created(ctx: dict, payload: dict[str, Any]) -> dict:
    return await _process_order(ctx, payload, OrderStatus.DRAFT, "ORDER_CREATED")


async def process_order_paid(ctx: dict, payload: dict[str, Any]) -> dict:
    return await _process_order(ctx, payload, OrderStatus.CONFIRMED, "ORDER_FULLY_PAID")


async def process_order_cancelled(ctx: dict, payload: dict[str, Any]) -> dict:
    return await _process_order(ctx, payload, OrderStatus.CANCELLED, "ORDER_CANCELLED")
