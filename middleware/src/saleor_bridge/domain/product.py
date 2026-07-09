"""Product domain model (Odoo product.template → Saleor Product + single variant).

A simple product maps to one Saleor Product with one dummy Variant sharing the
same SKU (ADR-0012). Stock is out of scope here (ADR-0014).
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
    list_price: Decimal  # sale price (round 2), channel currency (UZS)
    cost_price: Decimal = Decimal(0)  # standard_price (not pushed to Saleor)
    barcode: str | None = None
    active: bool = True
    write_date: str | None = None  # Odoo write_date — for the divergence marker
    has_variants: bool = False  # has attribute_line_ids → variant sync owns reconcile
