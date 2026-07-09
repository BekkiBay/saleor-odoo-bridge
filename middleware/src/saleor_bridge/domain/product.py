"""Product domain model (Odoo product.template → Saleor Product + single variant).

Phase 3.2: simple product → один Saleor Product + один dummy Variant с тем же SKU
(ADR-0012). Stock вне scope (ADR-0014).
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel


class Product(BaseModel):
    external_id: str  # Odoo product.template id as string
    sku: str  # default_code
    name: str
    description: str | None = None  # description_sale (plain text)
    category_external_id: str  # Odoo categ_id (as string)
    list_price: Decimal  # цена продажи (round 2), валюта канала (UZS)
    cost_price: Decimal = Decimal(0)  # standard_price (не пушим в Saleor в 3.2)
    barcode: str | None = None
    active: bool = True
    write_date: str | None = None  # Odoo write_date — для divergence-метки
    has_variants: bool = False  # есть attribute_line_ids → варианты owns reconcile (Phase 3.5)
