"""sale.order: canonical fulfillment status (unified across storefront + Odoo).

Single source of the customer-facing 5-step status. Computed from Odoo's own
state + pickings + a manual delivered flag, displayed in Odoo, and pushed to
Saleor order metadata (fulfillment_status) by the middleware so the storefront
reads the same value. Mapping lives in models/fulfillment_status.py (pure,
unit-tested).
"""
from odoo import api, fields, models

from .fulfillment_status import compute_fulfillment_status

_STATUS_SELECTION = [
    ("paid", "Paid"),
    ("assembling", "Assembling"),
    ("shipped", "Shipped"),
    ("delivered", "Delivered"),
    ("cancelled", "Cancelled"),
]


class SaleOrder(models.Model):
    _inherit = "sale.order"

    delivered_to_customer = fields.Boolean(
        string="Delivered to customer",
        copy=False,
        help="Set by warehouse/courier staff once the order reaches the buyer. "
             "Moves the unified status to 'Delivered'.",
    )
    fulfillment_status = fields.Selection(
        selection=_STATUS_SELECTION,
        string="Fulfillment status",
        compute="_compute_fulfillment_status",
        store=True,
        help="Unified order status as the customer sees it. Source of truth; "
             "pushed to Saleor order metadata under the key 'fulfillment_status'.",
    )

    @api.depends("state", "delivered_to_customer", "picking_ids.state")
    def _compute_fulfillment_status(self):
        for so in self:
            so.fulfillment_status = compute_fulfillment_status(
                so.state,
                so.delivered_to_customer,
                any(p.state == "done" for p in so.picking_ids),
            )
