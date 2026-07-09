"""Placeholder для расширения ir.actions.server.

В Phase 3.0 — пустой. В Phase 3.2+ здесь будет helper для регистрации
webhook server-actions при инсталле модуля (через data files), плюс
custom signing (HMAC headers поверх native Odoo `state='webhook'`).
"""

from odoo import models


class IrActionsServer(models.Model):
    _inherit = "ir.actions.server"
