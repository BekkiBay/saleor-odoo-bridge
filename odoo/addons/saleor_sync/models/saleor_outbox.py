"""Outbound events buffer Odoo → Saleor (audit + debug, Phase 3.2).

Не критичен для функциональности: даёт оператору видимость «что отправилось,
что нет». Заполняется серверным action'ом при каждом outbound-событии (см.
models/product_sync.py + data/base_automation_data.xml).
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
            ("state_change", "State change"),  # Phase 3.4: sale.order state
            ("shipped", "Shipped"),            # Phase 3.4: stock.picking done
        ],
        required=True,
    )
    payload = fields.Text(help="JSON snapshot отправленного в middleware.")
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
