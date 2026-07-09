"""Stock domain model (Odoo stock.quant → Saleor Stock per warehouse).

Phase 3.3: агрегируем internal-quant'ы товара в одно число на склад (ADR-0015),
применяем safety buffer на выходе (ADR-0016). Safety buffer + negative-clamp —
единственная точка трансформации перед push в Saleor.
"""

from __future__ import annotations

from pydantic import BaseModel


class Warehouse(BaseModel):
    external_id: str  # Odoo stock.warehouse id (as string)
    name: str
    slug: str  # уникальный slug для Saleor: f"{code}-{external_id}" (ADR-0015)


class StockLevel(BaseModel):
    """Агрегированный остаток варианта на одном складе.

    `raw_quantity` — сырой агрегат из Odoo (может быть отрицательным).
    `available_quantity` (== `display_quantity`) — то, что пушим в Saleor:
    `MAX(raw - safety_buffer, 0)` (ADR-0016). MAX(..,0) заодно clamp'ит negative.
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
        """То, что пушим в Saleor (alias available_quantity)."""
        return self.available_quantity
