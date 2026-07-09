"""domain.Order → sale.order operations (Odoo JSON-2)."""

from __future__ import annotations

from decimal import Decimal

import structlog

from saleor_bridge.adapters.odoo import product as product_adapter
from saleor_bridge.adapters.odoo import tax as tax_adapter
from saleor_bridge.domain.order import Order
from saleor_bridge.odoo.client import OdooClient

log = structlog.get_logger()


class UnmappableSku(RuntimeError):
    """A Saleor order SKU has no Odoo product — catalog desync. Retryable."""


_SO = "sale.order"
_SOL = "sale.order.line"
_PRODUCT = "product.product"

# ADR-0020: writes originating from Saleor events carry this context so Odoo's
# outbound automation does NOT emit an echo event back to Saleor.
_SKIP_CTX = {"saleor_sync_skip": True}

_currency_cache: dict[str, int | None] = {}


async def resolve_currency_id(odoo: OdooClient, code: str) -> int | None:
    if code in _currency_cache:
        return _currency_cache[code]
    rows = await odoo.search_read("res.currency", [("name", "=", code)], ["id"], limit=1)
    cid = rows[0]["id"] if rows else None
    _currency_cache[code] = cid
    return cid


async def resolve_product_id(odoo: OdooClient, sku: str) -> int | None:
    """ADR-0007: lookup product.product by default_code (SKU)."""
    if not sku:
        return None
    rows = await odoo.search_read(
        _PRODUCT, [("default_code", "=", sku)], ["id"], limit=2
    )
    if len(rows) == 1:
        return rows[0]["id"]
    if len(rows) > 1:
        log.warning("sku_collision", sku=sku, ids=[r["id"] for r in rows])
        return rows[0]["id"]  # fall back to the first one, already logged
    return None


async def find_order_id(odoo: OdooClient, order: Order) -> int | None:
    rows = await odoo.search_read(
        _SO, [("client_order_ref", "=", order.client_order_ref)], ["id"], limit=1
    )
    return rows[0]["id"] if rows else None


async def build_order_lines(odoo: OdooClient, order: Order) -> list:
    """Build sale.order.line command list. price_unit = NET; tax_ids from the line
    rate (P0). Unmappable SKU raises UnmappableSku (retryable — catalog desync)."""
    commands = []
    for line in order.lines:
        product_id = await resolve_product_id(odoo, line.sku)
        if product_id is None:
            log.warning("line_unmappable", sku=line.sku, name=line.product_name)
            raise UnmappableSku(line.sku)
        vals = {
            "product_id": product_id,
            "name": line.product_name or line.sku,
            "product_uom_qty": line.quantity,
            "price_unit": float(line.net_unit_price or line.unit_price),
        }
        if line.tax_rate and line.tax_rate > 0:
            tax = await tax_adapter.resolve_sale_tax(odoo, line.tax_rate)
            vals["tax_ids"] = [(6, 0, [tax])]
        commands.append((0, 0, vals))
    return commands


async def create_draft_order(
    odoo: OdooClient,
    order: Order,
    partner_id: int,
    invoice_id: int | None,
    shipping_id: int | None,
    shipping_sku: str = "SHIPPING",
) -> int:
    """Create sale.order in state draft. Returns order_id."""
    line_cmds = await build_order_lines(odoo, order)
    if order.shipping_net and order.shipping_net > 0:
        ship_product = await product_adapter.resolve_shipping_product(odoo, shipping_sku)
        ship_vals = {
            "product_id": ship_product,
            "name": order.shipping_method_name or "Shipping",
            "product_uom_qty": 1,
            "price_unit": float(order.shipping_net),
        }
        if order.shipping_tax_rate and order.shipping_tax_rate > 0:
            ship_tax = await tax_adapter.resolve_sale_tax(odoo, order.shipping_tax_rate)
            ship_vals["tax_ids"] = [(6, 0, [ship_tax])]
        line_cmds.append((0, 0, ship_vals))
    vals = {
        "partner_id": partner_id,
        "partner_invoice_id": invoice_id or partner_id,
        "partner_shipping_id": shipping_id or partner_id,
        "client_order_ref": order.client_order_ref,
        "order_line": line_cmds,
    }
    if order.discounts or order.voucher_code:
        parts = list(order.discounts)
        if order.voucher_code:
            parts.append(f"Voucher code: {order.voucher_code}")
        vals["note"] = "Saleor discounts — " + "; ".join(parts)
    currency_id = await resolve_currency_id(odoo, order.currency)
    if currency_id:
        vals["currency_id"] = currency_id
    if order.created_at:
        vals["date_order"] = order.created_at.isoformat(sep=" ", timespec="seconds")

    # skip-guard: creating a sale.order from a Saleor event must not echo-push (ADR-0020)
    res = await odoo.call(_SO, "create", vals_list=[vals], context=_SKIP_CTX)
    order_id = res[0] if isinstance(res, list) else res
    return order_id


def order_totals_match(odoo_total: Decimal, saleor_total: Decimal, tolerance: int) -> bool:
    """True if the two order totals agree within `tolerance` (minor units)."""
    return abs(Decimal(odoo_total) - Decimal(saleor_total)) <= tolerance


async def fetch_amount_total(odoo: OdooClient, order_id: int) -> Decimal:
    rows = await odoo.read(_SO, [order_id], ["amount_total"])
    return Decimal(str(rows[0]["amount_total"])) if rows else Decimal("0")


async def fetch_state(odoo: OdooClient, order_id: int) -> dict | None:
    """Current state of a sale.order for outbound state-sync."""
    rows = await odoo.read(_SO, [order_id], ["state", "name"])
    return rows[0] if rows else None


async def fetch_fulfillment_status(odoo: OdooClient, order_id: int) -> str | None:
    """Canonical fulfillment_status of a sale.order for outbound metadata push.

    Selection fields read as the key string (e.g. 'shipped') or False if unset →
    normalise False/missing to None.
    """
    rows = await odoo.read(_SO, [order_id], ["fulfillment_status"])
    if not rows:
        return None
    return rows[0].get("fulfillment_status") or None


async def confirm_order(odoo: OdooClient, order_id: int) -> None:
    """action_confirm → state 'sale'. Idempotent: checks state first.

    Passes the saleor_sync_skip context (ADR-0020): the confirmation came from
    Saleor, so we don't echo-push the state back.
    """
    rows = await odoo.read(_SO, [order_id], ["state"])
    state = rows[0]["state"] if rows else None
    if state == "sale":
        log.info("order_already_confirmed", order_id=order_id)
        return
    if state == "cancel":
        log.warning("order_cancelled_cannot_confirm", order_id=order_id)
        return
    await odoo.call(_SO, "action_confirm", ids=[order_id], context=_SKIP_CTX)


async def cancel_order(odoo: OdooClient, order_id: int) -> None:
    rows = await odoo.read(_SO, [order_id], ["state"])
    state = rows[0]["state"] if rows else None
    if state == "cancel":
        log.info("order_already_cancelled", order_id=order_id)
        return
    # action_cancel — public. _action_cancel is private (RPC blocked in Odoo 19).
    # skip-guard context (ADR-0020): cancellation came from Saleor — don't echo-push.
    await odoo.call(_SO, "action_cancel", ids=[order_id], context=_SKIP_CTX)
