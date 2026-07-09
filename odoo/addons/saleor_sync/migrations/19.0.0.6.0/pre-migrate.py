"""Rename the brand-specific order-status fields to neutral names.

`delivered_to_customer` (was `justix_delivered`) holds manually entered data —
a plain stored Boolean set by warehouse staff. Odoo would create a fresh, empty
column for the new field name and leave the old one orphaned, silently losing
every recorded delivery flag. Rename the column instead.

`fulfillment_status` (was `justix_status`) is a stored *computed* field, so Odoo
recomputes it on upgrade. Dropping the old column is enough.

The renamed views and automation rule also need their old records removed. Their
XML ids changed, so the loader would otherwise create new records and leave the
old ones behind — a duplicate inherited view on sale.order, and (because
base_automation_data.xml is noupdate="1") an untracked automation rule that
keeps firing.
"""

_TABLE_BY_MODEL = {
    "ir.ui.view": "ir_ui_view",
    "base.automation": "base_automation",
}

_OLD_XML_IDS = (
    "view_order_form_justix_status",
    "view_order_tree_justix_status",
    "auto_sync_sale_order_justix_status",
)


def _column_exists(cr, table, column):
    cr.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = %s AND column_name = %s",
        (table, column),
    )
    return cr.fetchone() is not None


def _table_exists(cr, table):
    cr.execute("SELECT to_regclass(%s)", (f"public.{table}",))
    return cr.fetchone()[0] is not None


def _drop_renamed_records(cr):
    """Delete the records behind the old external IDs, then the IDs themselves."""
    cr.execute(
        "SELECT name, model, res_id FROM ir_model_data "
        "WHERE module = 'saleor_sync' AND name IN %s",
        (_OLD_XML_IDS,),
    )
    for name, model, res_id in cr.fetchall():
        table = _TABLE_BY_MODEL.get(model)
        if table and _table_exists(cr, table):
            cr.execute(f"DELETE FROM {table} WHERE id = %s", (res_id,))  # noqa: S608
        cr.execute(
            "DELETE FROM ir_model_data WHERE module = 'saleor_sync' AND name = %s",
            (name,),
        )

    # The auto-generated external ID of the renamed field.
    cr.execute(
        "DELETE FROM ir_model_data "
        "WHERE module = 'saleor_sync' AND name = 'field_sale_order__justix_status'"
    )


def migrate(cr, version):
    if not version:
        return

    # Preserve manually entered delivery flags.
    if _column_exists(cr, "sale_order", "justix_delivered"):
        if _column_exists(cr, "sale_order", "delivered_to_customer"):
            cr.execute("ALTER TABLE sale_order DROP COLUMN justix_delivered")
        else:
            cr.execute(
                "ALTER TABLE sale_order "
                "RENAME COLUMN justix_delivered TO delivered_to_customer"
            )

    # Stored compute field — recomputed on upgrade, old column is dead weight.
    if _column_exists(cr, "sale_order", "justix_status"):
        cr.execute("ALTER TABLE sale_order DROP COLUMN justix_status")

    _drop_renamed_records(cr)
