"""Outbound events buffer Odoo → Saleor (audit + debug).

Not critical for functionality: gives an operator visibility into what was
sent and what wasn't. Populated by a server action on every outbound event
(see models/product_sync.py + data/base_automation_data.xml).
"""

from odoo import fields, models


class SaleorOutbox(models.Model):
    _name = "saleor.outbox"
    _description = "Outbound events to Saleor (audit + debug)"
    _order = "create_date desc"

    model_name = fields.Char(required=True, index=True)
    odoo_id = fields.Integer(required=True, index=True)
    action = fields.Selection(
        [
            ("create", "Create"),
            ("write", "Update"),
            ("unlink", "Archive"),
            ("state_change", "State change"),  # sale.order state
            ("shipped", "Shipped"),            # stock.picking done
        ],
        required=True,
    )
    payload = fields.Text(help="JSON snapshot of what was sent to the middleware.")
    state = fields.Selection(
        [
            ("sent", "Sent to middleware"),
            ("confirmed", "Confirmed by middleware"),
            ("failed", "Failed"),
        ],
        default="sent",
        required=True,
        index=True,
    )
    response_code = fields.Integer()
    error_message = fields.Text()
