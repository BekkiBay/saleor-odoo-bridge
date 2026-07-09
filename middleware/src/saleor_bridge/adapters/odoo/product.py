"""Read product.template из Odoo (JSON-2) → domain.Product.

Also provides resolve_shipping_product for P0 order financials (shipping line).
"""

from __future__ import annotations

import base64
import binascii
from decimal import ROUND_HALF_UP, Decimal

from saleor_bridge.domain.product import Product
from saleor_bridge.odoo.client import OdooClient

_MODEL = "product.template"
_PRODUCT = "product.product"
_cache: dict[str, int] = {}


class ShippingProductNotConfigured(RuntimeError):
    """No Odoo product with the configured shipping default_code — config error."""


async def resolve_shipping_product(odoo: OdooClient, sku: str) -> int:
    """Find product.product by default_code == sku. Cached. Raises if missing."""
    if sku in _cache:
        return _cache[sku]
    rows = await odoo.search_read(_PRODUCT, [("default_code", "=", sku)], ["id"], limit=1)
    if not rows:
        raise ShippingProductNotConfigured(f"no product.product with default_code={sku!r}")
    _cache[sku] = rows[0]["id"]
    return _cache[sku]


_FIELDS = [
    "id", "name", "default_code", "categ_id", "list_price", "standard_price",
    "barcode", "description_sale", "active", "write_date", "attribute_line_ids",
]


def _m2o_id(value) -> int | None:
    if isinstance(value, (list, tuple)) and value:
        return int(value[0])
    return None


def _money(value) -> Decimal:
    """Odoo float price → Decimal с 2 знаками (см. подводные камни: precision)."""
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def row_to_product(row: dict) -> Product:
    categ_id = _m2o_id(row.get("categ_id"))
    return Product(
        external_id=str(row["id"]),
        sku=(row.get("default_code") or "").strip() or f"odoo-{row['id']}",
        name=row["name"],
        description=(row.get("description_sale") or None),
        category_external_id=str(categ_id) if categ_id is not None else "",
        list_price=_money(row.get("list_price")),
        cost_price=_money(row.get("standard_price")),
        barcode=(row.get("barcode") or None),
        active=bool(row.get("active", True)),
        write_date=(row.get("write_date") or None),
        has_variants=bool(row.get("attribute_line_ids")),
    )


async def fetch_product(odoo: OdooClient, odoo_id: int) -> Product | None:
    rows = await odoo.read(_MODEL, [odoo_id], _FIELDS)
    return row_to_product(rows[0]) if rows else None


async def fetch_product_image(odoo: OdooClient, odoo_id: int) -> bytes | None:
    """Main product image (image_1920) as raw bytes, or None if unset."""
    rows = await odoo.read(_MODEL, [odoo_id], ["image_1920"])
    if not rows:
        return None
    raw = rows[0].get("image_1920")
    if not raw:
        return None
    try:
        return base64.b64decode(raw)
    except (binascii.Error, ValueError):
        return None


async def list_active_product_ids(odoo: OdooClient) -> list[int]:
    # sale_ok=True исключает не-витринные товары (напр. service-продукт «доставка»,
    # который добавляет модуль stock_delivery, Phase 3.4) — в каталог Saleor он не идёт.
    return await odoo.search(_MODEL, [("active", "=", True), ("sale_ok", "=", True)])


async def list_products(odoo: OdooClient, ids: list[int]) -> list[Product]:
    if not ids:
        return []
    rows = await odoo.read(_MODEL, ids, _FIELDS)
    return [row_to_product(r) for r in rows]
