"""Variant/Attribute domain models (Phase 3.5).

Odoo product.attribute → Saleor Attribute (DROPDOWN, ADR-0027).
Odoo product.product → Saleor ProductVariant (SKU = default_code, ADR-0024).
Цена варианта = template.list_price + PTAV.price_extra (Odoo считает в lst_price,
ADR-0026). PTAV напрямую НЕ синкаем — используем для резолва attribute values.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class AttributeValue(BaseModel):
    external_id: str  # Odoo product.attribute.value id (as string)
    name: str
    color_hex: str | None = None  # html_color — для swatch, Phase 4 (ADR-0027)


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
    sku: str  # default_code — primary key между системами (ADR-0024)
    price: Decimal  # lst_price (= template.list_price + price_extra), валюта канала
    cost: Decimal | None = None  # standard_price (не пушим в MVP)
    barcode: str | None = None
    attributes: list[VariantAttributeAssignment] = []
    active: bool = True
