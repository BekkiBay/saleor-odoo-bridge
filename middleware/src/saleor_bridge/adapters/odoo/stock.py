"""Read остатков из Odoo (stock.quant) → domain.StockLevel.

Агрегация по варианту: sum(quantity) по internal-локациям (ADR-0015, ADR-0017).
Один склад MVP → один StockLevel на вариант. Safety buffer применяет домен
(ADR-0016), здесь только сырой агрегат.
"""

from __future__ import annotations

import math

from saleor_bridge.adapters.saleor.slug import slugify
from saleor_bridge.domain.stock import StockLevel, Warehouse
from saleor_bridge.odoo.client import OdooClient

_QUANT = "stock.quant"
_WAREHOUSE = "stock.warehouse"
_VARIANT = "product.product"

# Только реальный складской остаток: internal-локации (не customer/supplier/inventory).
_INTERNAL = ("location_id.usage", "=", "internal")


def _m2o_id(value) -> int | None:
    if isinstance(value, (list, tuple)) and value:
        return int(value[0])
    return None


def _floor_qty(total: float) -> int:
    """Odoo quantity = float; Saleor stock = Int. Floor — консервативно (не оверселл)."""
    return math.floor(total)


async def fetch_default_warehouse(odoo: OdooClient) -> Warehouse | None:
    """Первый stock.warehouse (single-warehouse MVP, ADR-0015)."""
    rows = await odoo.search_read(_WAREHOUSE, [], ["id", "name", "code"], limit=1)
    if not rows:
        return None
    r = rows[0]
    code = (r.get("code") or "WH").strip()
    return Warehouse(external_id=str(r["id"]), name=r["name"], slug=f"{slugify(code)}-{r['id']}")


async def fetch_variant_ref(odoo: OdooClient, pp_id: int) -> dict | None:
    """product.product → {sku, template_id}. template_id нужен для catalog-binding."""
    rows = await odoo.read(_VARIANT, [pp_id], ["default_code", "product_tmpl_id"])
    if not rows:
        return None
    r = rows[0]
    sku = (r.get("default_code") or "").strip() or f"odoo-{pp_id}"
    return {"sku": sku, "template_id": _m2o_id(r.get("product_tmpl_id"))}


async def list_variant_ids_for_template(odoo: OdooClient, template_id: int) -> list[int]:
    return await odoo.search(_VARIANT, [("product_tmpl_id", "=", template_id)])


async def fetch_aggregated_stock(
    odoo: OdooClient,
    pp_id: int,
    warehouse: Warehouse,
    *,
    safety_buffer: int,
) -> list[StockLevel]:
    """Для одного product.product — агрегат остатка per warehouse.

    MVP: все internal-quant'ы → один StockLevel (default warehouse). Список —
    задел под multi-warehouse (Phase 4).
    """
    ref = await fetch_variant_ref(odoo, pp_id)
    sku = ref["sku"] if ref else f"odoo-{pp_id}"
    quants = await odoo.search_read(_QUANT, [("product_id", "=", pp_id), _INTERNAL], ["quantity"])
    total = sum(float(q.get("quantity") or 0) for q in quants)
    return [
        StockLevel(
            variant_sku=sku,
            warehouse_external_id=warehouse.external_id,
            raw_quantity=_floor_qty(total),
            safety_buffer=safety_buffer,
        )
    ]


async def fetch_all_aggregated_stock(
    odoo: OdooClient,
    warehouse: Warehouse,
    *,
    safety_buffer: int,
) -> dict[str, StockLevel]:
    """sku → StockLevel для всех активных вариантов (для reconcile). 2 read'а."""
    pp_ids = await odoo.search(_VARIANT, [("active", "=", True)])
    if not pp_ids:
        return {}
    refs = await odoo.read(_VARIANT, pp_ids, ["default_code"])
    quants = await odoo.search_read(
        _QUANT, [("product_id", "in", pp_ids), _INTERNAL], ["product_id", "quantity"]
    )
    totals: dict[int, float] = {}
    for q in quants:
        pid = _m2o_id(q.get("product_id"))
        if pid is not None:
            totals[pid] = totals.get(pid, 0.0) + float(q.get("quantity") or 0)

    out: dict[str, StockLevel] = {}
    for r in refs:
        sku = (r.get("default_code") or "").strip() or f"odoo-{r['id']}"
        out[sku] = StockLevel(
            variant_sku=sku,
            warehouse_external_id=warehouse.external_id,
            raw_quantity=_floor_qty(totals.get(r["id"], 0.0)),
            safety_buffer=safety_buffer,
        )
    return out
