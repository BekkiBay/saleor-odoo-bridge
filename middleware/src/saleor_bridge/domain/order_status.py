"""Order-status domain (Odoo → Saleor).

The worker re-reads state from Odoo (ADR-0019), so heavyweight transition models
aren't needed — we keep only what's actually passed to the Saleor mutations.
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
