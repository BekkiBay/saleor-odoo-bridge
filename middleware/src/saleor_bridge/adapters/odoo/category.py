"""Read product.category из Odoo (JSON-2) → domain.ProductCategory."""

from __future__ import annotations

from saleor_bridge.domain.category import ProductCategory
from saleor_bridge.odoo.client import OdooClient

_MODEL = "product.category"
_FIELDS = ["id", "name", "parent_id", "complete_name"]


def _m2o_id(value) -> int | None:
    """JSON-2 many2one → [id, name] | False."""
    if isinstance(value, (list, tuple)) and value:
        return int(value[0])
    return None


def row_to_category(row: dict) -> ProductCategory:
    parent_id = _m2o_id(row.get("parent_id"))
    return ProductCategory(
        external_id=str(row["id"]),
        name=row["name"],
        parent_external_id=str(parent_id) if parent_id is not None else None,
        complete_name=row.get("complete_name") or row["name"],
    )


async def fetch_category(odoo: OdooClient, odoo_id: int) -> ProductCategory | None:
    rows = await odoo.read(_MODEL, [odoo_id], _FIELDS)
    return row_to_category(rows[0]) if rows else None


async def list_categories(odoo: OdooClient, ids: list[int]) -> list[ProductCategory]:
    if not ids:
        return []
    rows = await odoo.read(_MODEL, ids, _FIELDS)
    return [row_to_category(r) for r in rows]
