"""Pure canonical-status mapping. NO Odoo imports — standalone-unit-testable.

Single definition of the customer-facing 5-step status. Used by the
sale.order computed field (Odoo display + Saleor metadata push). See spec
2026-06-22-unified-order-status-odoo-design.md.
"""
from __future__ import annotations

# Selection keys (must match the storefront CANONICAL map, lower-case).
PAID = "paid"
ASSEMBLING = "assembling"
SHIPPED = "shipped"
DELIVERED = "delivered"
CANCELLED = "cancelled"


def compute_justix_status(state, delivered, has_done_picking):
    """Map Odoo state + delivered flag + picking state → canonical status.

    Precedence (top-down): cancel > delivered > shipped > assembling > paid.
    """
    if state == "cancel":
        return CANCELLED
    if delivered:
        return DELIVERED
    if has_done_picking:
        return SHIPPED
    if state in ("sale", "done"):
        return ASSEMBLING
    return PAID  # draft / anything else → step 1
