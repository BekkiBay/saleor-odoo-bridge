"""External ID mapping table: Saleor ↔ Odoo.

See ADR-0003 (custom module) and ADR-0007 (SKU as natural key + mapping
fallback).

Records are created automatically as records are synced between the two
systems (see models/product_sync.py and data/base_automation_data.xml).
"""

from odoo import api, fields, models


class SaleorBinding(models.Model):
    _name = "saleor.binding"
    _description = "External ID mapping Saleor ↔ Odoo"
    _rec_name = "odoo_ref"
    _order = "id desc"

    model_name = fields.Char(
        string="Model",
        required=True,
        index=True,
        help="Technical name of the model (res.partner, product.template, sale.order, ...)",
    )
    odoo_id = fields.Many2oneReference(
        string="Odoo Record",
        model_field="model_name",
        required=True,
        help="ID of the record in Odoo. Resolved via model_name.",
    )
    saleor_id = fields.Char(
        string="Saleor ID",
        required=True,
        index=True,
        help="Base64 global ID from Saleor (e.g. 'UHJvZHVjdDox' = 'Product:1').",
    )
    odoo_ref = fields.Char(
        string="Reference",
        compute="_compute_odoo_ref",
        store=False,
        help="Human-readable display name (computed for the UI).",
    )
    last_sync_in = fields.Datetime(
        string="Last Sync Saleor → Odoo",
        help="When we last accepted a change coming from Saleor.",
    )
    last_sync_out = fields.Datetime(
        string="Last Sync Odoo → Saleor",
        help="When we last sent a change to Saleor.",
    )
    sync_state = fields.Selection(
        [
            ("pending", "Pending"),
            ("synced", "Synced"),
            ("failed", "Failed"),
            ("diverged", "Diverged"),
        ],
        default="pending",
        required=True,
        index=True,
    )
    error_message = fields.Text(
        string="Last Error",
        help="Details of the last failed sync (see ADR-0008).",
    )

    # Odoo 19 replaced _sql_constraints with models.Constraint.
    _unique_saleor_id_per_model = models.Constraint(
        "UNIQUE(model_name, saleor_id)",
        "Saleor ID must be unique per model.",
    )

    def init(self):
        """Partial unique index (model_name, odoo_id) — a backstop against
        duplicate outbound bindings (hardening on top of the Redis lock in
        the middleware).

        WHERE odoo_id != 0 — excludes placeholders: the singleton
        product.type and inbound failed placeholders (mark_failed) use
        odoo_id=0.
        """
        self.env.cr.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS saleor_binding_model_odoo_uniq
            ON saleor_binding (model_name, odoo_id) WHERE odoo_id != 0
            """
        )

    @api.depends("model_name", "odoo_id")
    def _compute_odoo_ref(self):
        for rec in self:
            if not rec.model_name or not rec.odoo_id:
                rec.odoo_ref = ""
                continue
            try:
                target = self.env[rec.model_name].browse(rec.odoo_id)
                rec.odoo_ref = target.display_name if target.exists() else f"<missing #{rec.odoo_id}>"
            except KeyError:
                rec.odoo_ref = f"<unknown model {rec.model_name}>"
