"""Stock domain model (Odoo stock.quant → Saleor Stock per warehouse).

We aggregate the product's internal quants into a single number per warehouse
(ADR-0015), and apply a safety buffer on the way out (ADR-0016). Safety buffer
+ negative-clamp is the single transformation point before pushing to Saleor.
"""

from __future__ import annotations

from pydantic import BaseModel


class Warehouse(BaseModel):
    external_id: str  # Odoo stock.warehouse id (as string)
    name: str
    slug: str  # unique slug for Saleor: f"{code}-{external_id}" (ADR-0015)


class StockLevel(BaseModel):
    """Aggregated stock level for a variant at a single warehouse.

    `raw_quantity` — the raw aggregate from Odoo (can be negative).
    `available_quantity` (== `display_quantity`) — what we push to Saleor:
    `MAX(raw - safety_buffer, 0)` (ADR-0016). MAX(..,0) also clamps negative values.
    """

    variant_sku: str
    warehouse_external_id: str
    raw_quantity: int
    safety_buffer: int = 1

    @property
    def available_quantity(self) -> int:
        return max(self.raw_quantity - self.safety_buffer, 0)

    @property
    def display_quantity(self) -> int:
        """What we push to Saleor (alias available_quantity)."""
        return self.available_quantity
