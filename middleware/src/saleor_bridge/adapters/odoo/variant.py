"""Read product.product (variant) из Odoo (JSON-2) → domain.Variant (Phase 3.5).

Цена варианта = lst_price (Odoo считает = template.list_price + sum(PTAV.price_extra),
ADR-0026) — читаем готовое значение, не суммируем сами. Attribute-assignments
декодим из product_template_attribute_value_ids (PTAV) → (attribute, value) пары.
SKU = default_code, fallback odoo-<id> (ADR-0024).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from saleor_bridge.domain.variants import Variant, VariantAttributeAssignment
from saleor_bridge.odoo.client import OdooClient

_VARIANT = "product.product"
_PTAV = "product.template.attribute.value"

_VARIANT_FIELDS = [
    "id", "default_code", "lst_price", "standard_price", "barcode", "active",
    "product_tmpl_id", "product_template_attribute_value_ids",
]
_PTAV_FIELDS = ["id", "attribute_id", "product_attribute_value_id"]


def _m2o_id(value) -> int | None:
    if isinstance(value, (list, tuple)) and value:
        return int(value[0])
    return None


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _sku(row: dict) -> str:
    return (row.get("default_code") or "").strip() or f"odoo-{row['id']}"


async def _ptav_map(odoo: OdooClient, ptav_ids: list[int]) -> dict[int, VariantAttributeAssignment]:
    """PTAV id → assignment (attribute_external_id, value_external_id). Один read."""
    if not ptav_ids:
        return {}
    rows = await odoo.read(_PTAV, ptav_ids, _PTAV_FIELDS)
    out: dict[int, VariantAttributeAssignment] = {}
    for r in rows:
        attr_id = _m2o_id(r.get("attribute_id"))
        val_id = _m2o_id(r.get("product_attribute_value_id"))
        if attr_id is None or val_id is None:
            continue
        out[r["id"]] = VariantAttributeAssignment(
            attribute_external_id=str(attr_id),
            value_external_id=str(val_id),
        )
    return out


def _row_to_variant(row: dict, ptav_map: dict[int, VariantAttributeAssignment]) -> Variant:
    assignments = [ptav_map[i] for i in (row.get("product_template_attribute_value_ids") or []) if i in ptav_map]
    return Variant(
        external_id=str(row["id"]),
        template_external_id=str(_m2o_id(row.get("product_tmpl_id")) or ""),
        sku=_sku(row),
        price=_money(row.get("lst_price")),
        cost=_money(row.get("standard_price")),
        barcode=(row.get("barcode") or None),
        attributes=assignments,
        active=bool(row.get("active", True)),
    )


async def fetch_variant(odoo: OdooClient, pp_id: int) -> Variant | None:
    rows = await odoo.read(_VARIANT, [pp_id], _VARIANT_FIELDS)
    if not rows:
        return None
    row = rows[0]
    ptav_map = await _ptav_map(odoo, row.get("product_template_attribute_value_ids") or [])
    return _row_to_variant(row, ptav_map)


async def fetch_variants_for_template(odoo: OdooClient, template_id: int) -> list[Variant]:
    """Все активные варианты шаблона. Батч-резолв PTAV (2 read'а суммарно)."""
    pp_ids = await odoo.search(_VARIANT, [("product_tmpl_id", "=", template_id), ("active", "=", True)])
    if not pp_ids:
        return []
    rows = await odoo.read(_VARIANT, pp_ids, _VARIANT_FIELDS)
    all_ptav_ids = sorted({i for r in rows for i in (r.get("product_template_attribute_value_ids") or [])})
    ptav_map = await _ptav_map(odoo, all_ptav_ids)
    return [_row_to_variant(r, ptav_map) for r in rows]
