"""ProductCategory domain model (Odoo product.category → Saleor Category)."""

from __future__ import annotations

from pydantic import BaseModel


class ProductCategory(BaseModel):
    external_id: str  # Odoo product.category id as string
    name: str
    parent_external_id: str | None = None  # None = root category
    complete_name: str = ""  # "Одежда / Платья" — для дебага и для slug
