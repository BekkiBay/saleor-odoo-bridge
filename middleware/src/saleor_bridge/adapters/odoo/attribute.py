"""Read product.attribute / product.attribute.value from Odoo (JSON-2) → domain.

Only DROPDOWN is supported (ADR-0027). create_variant='no_variant' attributes
are skipped in the MVP (this is a product-level "composition/material" attribute) —
fetch returns None.
"""

from __future__ import annotations

from saleor_bridge.domain.variants import Attribute, AttributeValue
from saleor_bridge.odoo.client import OdooClient

_ATTR = "product.attribute"
_VALUE = "product.attribute.value"

_ATTR_FIELDS = ["id", "name", "create_variant", "value_ids"]
_VALUE_FIELDS = ["id", "name", "html_color", "attribute_id"]


def _m2o_id(value) -> int | None:
    if isinstance(value, (list, tuple)) and value:
        return int(value[0])
    return None


def _row_to_value(row: dict) -> AttributeValue:
    return AttributeValue(
        external_id=str(row["id"]),
        name=row["name"],
        color_hex=(row.get("html_color") or None),
    )


async def fetch_attribute(odoo: OdooClient, odoo_id: int) -> Attribute | None:
    """product.attribute → Attribute with all its values. None for no_variant (skip MVP)."""
    rows = await odoo.read(_ATTR, [odoo_id], _ATTR_FIELDS)
    if not rows:
        return None
    row = rows[0]
    if row.get("create_variant") == "no_variant":
        return None  # product-level attribute (material/composition) — not synced
    value_ids = row.get("value_ids") or []
    values = await odoo.read(_VALUE, value_ids, _VALUE_FIELDS) if value_ids else []
    return Attribute(
        external_id=str(row["id"]),
        name=row["name"],
        values=[_row_to_value(v) for v in values],
    )


async def fetch_attribute_value(odoo: OdooClient, odoo_id: int) -> dict | None:
    """product.attribute.value → {value: AttributeValue, attribute_id: int}.

    attribute_id is needed to resolve the parent Saleor Attribute.
    """
    rows = await odoo.read(_VALUE, [odoo_id], _VALUE_FIELDS)
    if not rows:
        return None
    row = rows[0]
    return {"value": _row_to_value(row), "attribute_id": _m2o_id(row.get("attribute_id"))}
