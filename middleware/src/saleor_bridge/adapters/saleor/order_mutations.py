"""Saleor order lifecycle мутации Odoo → Saleor (Phase 3.4).

Idempotency: ПЕРЕД каждой мутацией читаем текущий статус и пропускаем, если заказ
уже в целевом состоянии (Saleor state-machine строгая — иначе error). Pure GraphQL;
binding / SKU-резолв — в usecase.
"""

from __future__ import annotations

import structlog

from saleor_bridge.adapters.saleor.common import SaleorError, query_data, run_mutation
from saleor_bridge.domain.order_status import FulfillmentLine
from saleor_bridge.saleor.client import SaleorClient
from saleor_bridge.usecases.result import SyncResult

log = structlog.get_logger()

_ORDER = """
query($id: ID!){
  order(id:$id){
    id number status isPaid paymentStatus
    fulfillments{ id status }
    lines{ id productSku quantity quantityToFulfill variant{ sku } }
  }
}
"""

_CONFIRM = """
mutation($id: ID!){ orderConfirm(id:$id){ order{ id status } errors{ field message code } } }
"""

_CANCEL = """
mutation($id: ID!){ orderCancel(id:$id){ order{ id status } errors{ field message code } } }
"""

_MARK_PAID = """
mutation($id: ID!){ orderMarkAsPaid(id:$id){ order{ id isPaid } errors{ field message code } } }
"""

_FULFILL = """
mutation($order: ID!, $input: OrderFulfillInput!){
  orderFulfill(order:$order, input:$input){
    fulfillments{ id status trackingNumber }
    errors{ field message code }
  }
}
"""

_UPDATE_METADATA = """
mutation($id: ID!, $input: [MetadataInput!]!){
  updateMetadata(id:$id, input:$input){
    item{ __typename ... on Order { id } }
    errors{ field message code }
  }
}
"""


async def fetch_order_status(client: SaleorClient, order_id: str) -> dict | None:
    data = await query_data(client, _ORDER, {"id": order_id})
    return data.get("order")


def _line_sku(line: dict) -> str | None:
    return line.get("productSku") or ((line.get("variant") or {}).get("sku"))


async def confirm_order(client: SaleorClient, order_id: str) -> SyncResult:
    order = await fetch_order_status(client, order_id)
    if order is None:
        return SyncResult(ok=False, message=f"saleor order {order_id} not found")
    status = order.get("status")
    if status != "UNCONFIRMED":
        log.info("order_confirm_skip", order_id=order_id, status=status)
        return SyncResult(ok=True, message=f"already {status}, confirm skipped")
    try:
        await run_mutation(client, _CONFIRM, {"id": order_id}, "orderConfirm")
    except SaleorError as exc:
        # Гонка: статус сменился между check и mutation. Трактуем как no-op.
        if "UNCONFIRMED" in str(exc):
            log.info("order_confirm_race_noop", order_id=order_id)
            return SyncResult(ok=True, message="confirm race no-op")
        raise
    log.info("order_confirmed", order_id=order_id)
    return SyncResult(ok=True, message="order confirmed")


async def cancel_order(client: SaleorClient, order_id: str) -> SyncResult:
    order = await fetch_order_status(client, order_id)
    if order is None:
        return SyncResult(ok=False, message=f"saleor order {order_id} not found")
    status = order.get("status")
    if status == "CANCELED":
        log.info("order_cancel_skip", order_id=order_id)
        return SyncResult(ok=True, message="already canceled")
    if status in ("FULFILLED", "PARTIALLY_FULFILLED", "RETURNED", "PARTIALLY_RETURNED"):
        # Saleor запрещает cancel после отгрузки — это return-flow (out of scope).
        log.warning("order_cancel_after_fulfill", order_id=order_id, status=status)
        return SyncResult(ok=False, message=f"cannot cancel {status} order (needs return flow)")
    await run_mutation(client, _CANCEL, {"id": order_id}, "orderCancel")
    log.info("order_cancelled", order_id=order_id)
    return SyncResult(ok=True, message="order cancelled")


async def mark_paid(client: SaleorClient, order_id: str) -> SyncResult:
    order = await fetch_order_status(client, order_id)
    if order is None:
        return SyncResult(ok=False, message=f"saleor order {order_id} not found")
    if order.get("isPaid") or order.get("paymentStatus") == "FULLY_CHARGED":
        log.info("order_mark_paid_skip", order_id=order_id)
        return SyncResult(ok=True, message="already paid")
    await run_mutation(client, _MARK_PAID, {"id": order_id}, "orderMarkAsPaid")
    log.info("order_marked_paid", order_id=order_id)
    return SyncResult(ok=True, message="order marked paid")


def build_fulfillment_lines(
    order_lines: list[dict], sku_qty: dict[str, int], warehouse_id: str
) -> list[FulfillmentLine]:
    """SKU→qty (из Odoo picking) → FulfillmentLine[] по Saleor order lines.

    quantity = min(отгружено в Odoo, ещё-не-зафулфилл в Saleor). Строки без
    остатка к фулфиллу или без совпадения SKU пропускаются.
    """
    lines: list[FulfillmentLine] = []
    for ol in order_lines:
        sku = _line_sku(ol)
        if not sku or sku not in sku_qty:
            continue
        to_fulfill = int(ol.get("quantityToFulfill") or 0)
        qty = min(sku_qty[sku], to_fulfill)
        if qty <= 0:
            continue
        lines.append(
            FulfillmentLine(saleor_order_line_id=ol["id"], quantity=qty, warehouse_id=warehouse_id)
        )
    return lines


async def fulfill_order(
    client: SaleorClient,
    order_id: str,
    *,
    sku_qty: dict[str, int],
    warehouse_id: str,
    tracking_number: str | None = None,
    notify: bool = True,
) -> SyncResult:
    order = await fetch_order_status(client, order_id)
    if order is None:
        return SyncResult(ok=False, message=f"saleor order {order_id} not found")
    status = order.get("status")
    if status in ("FULFILLED", "CANCELED"):
        log.info("order_fulfill_skip", order_id=order_id, status=status)
        return SyncResult(ok=True, message=f"{status}, fulfill skipped")

    lines = build_fulfillment_lines(order.get("lines") or [], sku_qty, warehouse_id)
    if not lines:
        log.info("order_fulfill_nolines", order_id=order_id, sku_qty=sku_qty)
        return SyncResult(ok=True, message="nothing to fulfill (already fulfilled / no SKU match)")

    fulfill_input: dict = {
        "lines": [
            {"orderLineId": ln.saleor_order_line_id,
             "stocks": [{"quantity": ln.quantity, "warehouse": ln.warehouse_id}]}
            for ln in lines
        ],
        "notifyCustomer": notify,
        "allowStockToBeExceeded": False,
    }
    if tracking_number:
        fulfill_input["trackingNumber"] = tracking_number

    payload = await run_mutation(
        client, _FULFILL, {"order": order_id, "input": fulfill_input}, "orderFulfill"
    )
    ffs = payload.get("fulfillments") or []
    log.info("order_fulfilled", order_id=order_id, lines=len(lines),
             tracking=tracking_number, fulfillments=[f.get("id") for f in ffs])
    return SyncResult(ok=True, message=f"fulfilled {len(lines)} line(s)")


async def update_order_metadata(
    client: SaleorClient, order_id: str, metadata: dict[str, str]
) -> SyncResult:
    """Write order metadata (canonical justix_status). Idempotent — rewriting the
    same key/value is harmless; no pre-read."""
    inp = [{"key": k, "value": v} for k, v in metadata.items()]
    await run_mutation(client, _UPDATE_METADATA, {"id": order_id, "input": inp}, "updateMetadata")
    log.info("order_metadata_updated", order_id=order_id, keys=list(metadata))
    return SyncResult(ok=True, message=f"metadata {list(metadata)} updated")
