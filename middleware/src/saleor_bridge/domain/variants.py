"""Variant/Attribute domain models.

Odoo product.attribute → Saleor Attribute (DROPDOWN, ADR-0027).
Odoo product.product → Saleor ProductVariant (SKU = default_code, ADR-0024).
Variant price = template.list_price + PTAV.price_extra (Odoo computes it in lst_price,
ADR-0026). PTAV is NOT synced directly — it's used to resolve attribute values.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class AttributeValue(BaseModel):
    external_id: str  # Odoo product.attribute.value id (as string)
    name: str
    color_hex: str | None = None  # html_color — for the color swatch (ADR-0027)


class Attribute(BaseModel):
    external_id: str  # Odoo product.attribute id (as string)
    name: str
    input_type: Literal["DROPDOWN"] = "DROPDOWN"  # MVP per ADR-0027
    values: list[AttributeValue] = []


class VariantAttributeAssignment(BaseModel):
    attribute_external_id: str  # Odoo product.attribute id
    value_external_id: str  # Odoo product.attribute.value id


class Variant(BaseModel):
    external_id: str  # Odoo product.product id (as string)
    template_external_id: str  # Odoo product.template id (as string)
    sku: str  # default_code — primary key between systems (ADR-0024)
    price: Decimal  # lst_price (= template.list_price + price_extra), channel currency
    cost: Decimal | None = None  # standard_price (not pushed in MVP)
    barcode: str | None = None
    attributes: list[VariantAttributeAssignment] = []
    active: bool = True
