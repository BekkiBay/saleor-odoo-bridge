"""Order-status domain (Odoo → Saleor, Phase 3.4).

Worker перечитывает состояние из Odoo (ADR-0019), поэтому тяжёлые transition-модели
не нужны — держим то, что реально передаётся в Saleor-мутации.
"""

from __future__ import annotations

from pydantic import BaseModel


class FulfillmentLine(BaseModel):
    saleor_order_line_id: str
    quantity: int
    warehouse_id: str  # Saleor Warehouse id (ADR-0015, single warehouse)


class FulfillmentEvent(BaseModel):
    odoo_picking_id: int
    saleor_order_id: str
    line_items: list[FulfillmentLine]
    tracking_number: str | None = None
    notify_customer: bool = True
