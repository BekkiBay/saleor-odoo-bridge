"""sale.order: canonical Justix status (unified across storefront + Odoo).

Single source of the customer-facing 5-step status. Computed from Odoo's own
state + pickings + a manual delivered flag, displayed in Odoo, and pushed to
Saleor order metadata (justix_status) by the middleware so the storefront reads
the same value. Mapping lives in models/justix_status.py (pure, unit-tested).
"""
from odoo import api, fields, models

from .justix_status import compute_justix_status

_STATUS_SELECTION = [
    ("paid", "Оплачен"),
    ("assembling", "Собирается"),
    ("shipped", "Отгружен"),
    ("delivered", "Доставлен"),
    ("cancelled", "Отменён"),
]


class SaleOrder(models.Model):
    _inherit = "sale.order"

    justix_delivered = fields.Boolean(
        string="Доставлен клиенту",
        copy=False,
        help="Отметка склада/курьера: заказ доставлен покупателю. "
             "Двигает единый статус в «Доставлен».",
    )
    justix_status = fields.Selection(
        selection=_STATUS_SELECTION,
        string="Статус Justix",
        compute="_compute_justix_status",
        store=True,
        help="Единый статус заказа, как его видит покупатель. Источник правды; "
             "пушится в Saleor metadata justix_status.",
    )

    @api.depends("state", "justix_delivered", "picking_ids.state")
    def _compute_justix_status(self):
        for so in self:
            so.justix_status = compute_justix_status(
                so.state,
                so.justix_delivered,
                any(p.state == "done" for p in so.picking_ids),
            )
