"""Read stock.picking + фактически отгруженные строки (Phase 3.4).

move_line_ids = фактические движения с done-количеством (`quantity`), в отличие от
move_ids (планируемые). Маппим product → SKU (default_code) для резолва Saleor
order line (ADR-0019, подводные камни).
"""

from __future__ import annotations

from saleor_bridge.odoo.client import OdooClient

_PICKING = "stock.picking"
_MOVE_LINE = "stock.move.line"
_PRODUCT = "product.product"


def _m2o_id(value) -> int | None:
    if isinstance(value, (list, tuple)) and value:
        return int(value[0])
    return None


async def fetch_picking_with_lines(odoo: OdooClient, picking_id: int) -> dict | None:
    """→ {state, sale_order_id, tracking, sku_qty: {SKU: done_qty}} или None."""
    rows = await odoo.read(
        _PICKING, [picking_id],
        ["state", "sale_id", "carrier_tracking_ref", "move_line_ids"],
    )
    if not rows:
        return None
    p = rows[0]

    sku_qty: dict[str, int] = {}
    line_ids = p.get("move_line_ids") or []
    if line_ids:
        mls = await odoo.read(_MOVE_LINE, line_ids, ["product_id", "quantity"])
        prod_ids = list({_m2o_id(ml.get("product_id")) for ml in mls if ml.get("product_id")})
        prods = await odoo.read(_PRODUCT, prod_ids, ["default_code"]) if prod_ids else []
        code_by_id = {pr["id"]: (pr.get("default_code") or "").strip() for pr in prods}
        for ml in mls:
            pid = _m2o_id(ml.get("product_id"))
            sku = code_by_id.get(pid)
            qty = int(ml.get("quantity") or 0)  # done qty (Odoo 17+ renamed from qty_done)
            if sku and qty > 0:
                sku_qty[sku] = sku_qty.get(sku, 0) + qty

    return {
        "state": p.get("state"),
        "sale_order_id": _m2o_id(p.get("sale_id")),
        "tracking": (p.get("carrier_tracking_ref") or None),
        "sku_qty": sku_qty,
    }
