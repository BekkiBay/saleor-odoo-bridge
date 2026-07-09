"""Migration 19.0.0.6.0: the field rename must not lose data.

`delivered_to_customer` (was `justix_delivered`) is a plain stored Boolean set by
warehouse staff. If the migration ever stops renaming the column, Odoo silently
creates an empty one and every recorded delivery flag is gone. That failure is
invisible until someone looks at an old order, so it is pinned here.

Driven with a fake cursor: no Odoo runtime, no Postgres.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_MIG = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "19.0.0.6.0"
    / "pre-migrate.py"
)
_spec = importlib.util.spec_from_file_location("pre_migrate", _MIG)
pre_migrate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pre_migrate)


class FakeCursor:
    """Records executed SQL and answers the introspection queries."""

    def __init__(self, columns: list[str], xml_ids: list[tuple[str, str, int]]) -> None:
        self.columns = set(columns)
        self.xml_ids = list(xml_ids)
        self.sql: list[str] = []
        self._one: tuple | None = None
        self._rows: list[tuple] = []

    def execute(self, query: str, params: tuple | None = None) -> None:
        flat = " ".join(query.split())
        self.sql.append(flat)
        lowered = flat.lower()
        if "information_schema.columns" in lowered:
            self._one = (1,) if params and params[1] in self.columns else None
        elif "to_regclass" in lowered:
            self._one = ("public.table",)
        elif lowered.startswith("select name, model, res_id from ir_model_data"):
            self._rows = self.xml_ids
        elif "rename column" in lowered:
            self.columns.discard("justix_delivered")
            self.columns.add("delivered_to_customer")
        elif "drop column" in lowered:
            for column in list(self.columns):
                if column in flat:
                    self.columns.discard(column)

    def fetchone(self) -> tuple | None:
        return self._one

    def fetchall(self) -> list[tuple]:
        return self._rows


def _sql_matching(cr: FakeCursor, needle: str) -> list[str]:
    return [s for s in cr.sql if needle in s]


def test_upgrade_renames_column_instead_of_dropping_it():
    cr = FakeCursor(["justix_delivered", "justix_status"], [])
    pre_migrate.migrate(cr, "19.0.0.5.0")

    assert _sql_matching(cr, "RENAME COLUMN justix_delivered TO delivered_to_customer"), (
        "manually recorded delivery flags would be lost"
    )
    assert not _sql_matching(cr, "DROP COLUMN justix_delivered")


def test_upgrade_drops_the_stored_computed_column():
    cr = FakeCursor(["justix_delivered", "justix_status"], [])
    pre_migrate.migrate(cr, "19.0.0.5.0")

    # fulfillment_status is recomputed on upgrade, so the old column is dead weight.
    assert _sql_matching(cr, "DROP COLUMN justix_status")


def test_upgrade_deletes_records_behind_renamed_external_ids():
    cr = FakeCursor(
        ["justix_status"],
        [
            ("view_order_form_justix_status", "ir.ui.view", 101),
            ("auto_sync_sale_order_justix_status", "base.automation", 201),
        ],
    )
    pre_migrate.migrate(cr, "19.0.0.5.0")

    # Without this the loader leaves an orphaned inherited view and a duplicate,
    # untracked automation rule (base_automation_data.xml is noupdate="1").
    assert _sql_matching(cr, "DELETE FROM ir_ui_view WHERE id = %s")
    assert _sql_matching(cr, "DELETE FROM base_automation WHERE id = %s")
    assert _sql_matching(cr, "DELETE FROM ir_model_data WHERE module = 'saleor_sync' AND name = %s")


def test_fresh_install_is_a_noop():
    cr = FakeCursor(["justix_delivered"], [])
    pre_migrate.migrate(cr, None)  # Odoo passes a falsy version on first install
    assert cr.sql == []


def test_rerunning_the_migration_is_idempotent():
    cr = FakeCursor(["delivered_to_customer"], [])
    pre_migrate.migrate(cr, "19.0.0.6.0")
    assert not _sql_matching(cr, "RENAME")


def test_partial_upgrade_drops_the_stale_column_and_keeps_the_new_one():
    cr = FakeCursor(["justix_delivered", "delivered_to_customer"], [])
    pre_migrate.migrate(cr, "19.0.0.5.0")

    assert _sql_matching(cr, "DROP COLUMN justix_delivered")
    assert not _sql_matching(cr, "RENAME")
    assert "delivered_to_customer" in cr.columns


@pytest.mark.parametrize("version", ["19.0.0.5.0", "19.0.0.4.0"])
def test_migration_runs_for_any_prior_version(version):
    cr = FakeCursor(["justix_delivered"], [])
    pre_migrate.migrate(cr, version)
    assert _sql_matching(cr, "RENAME COLUMN justix_delivered TO delivered_to_customer")
