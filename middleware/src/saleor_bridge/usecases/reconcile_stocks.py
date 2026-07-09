"""Reconcile: compares Odoo vs Saleor stock levels + optional auto-fix (ADR-0018).

Drift = `saleor_qty != MAX(odoo_raw - buffer, 0)`. A discrepancy of exactly the
buffer is normal (ADR-0016), NOT drift. The pure diff logic (`diff_stock`) is
kept separate from I/O for unit testing.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from saleor_bridge.adapters.odoo import stock as stock_adapter
from saleor_bridge.adapters.odoo.binding import BindingRepository
from saleor_bridge.adapters.saleor import stock_mutations as sm
from saleor_bridge.adapters.saleor.factory import get_saleor_client
from saleor_bridge.config import Settings
from saleor_bridge.domain.stock import StockLevel
from saleor_bridge.odoo.client import OdooClient

log = structlog.get_logger()


@dataclass
class ReconcileRow:
    sku: str
    warehouse: str
    odoo_raw: int
    saleor_qty: int
    expected: int  # MAX(odoo_raw - buffer, 0)
    diff: int  # saleor_qty - odoo_raw (=-buffer when consistent)
    drift: bool


def diff_stock(
    odoo_levels: dict[str, StockLevel],
    saleor_stocks: dict[str, dict],
    warehouse_slug: str,
) -> list[ReconcileRow]:
    """Pair of (Odoo aggregate, Saleor stock) → reconciliation rows. Pure function.

    Variants that aren't in Saleor (not yet in the catalog) are skipped.
    """
    rows: list[ReconcileRow] = []
    for sku, level in sorted(odoo_levels.items()):
        info = saleor_stocks.get(sku)
        if info is None:
            continue
        actual = int(info["total"])
        expected = level.display_quantity
        rows.append(
            ReconcileRow(
                sku=sku,
                warehouse=warehouse_slug,
                odoo_raw=level.raw_quantity,
                saleor_qty=actual,
                expected=expected,
                diff=actual - level.raw_quantity,
                drift=(actual != expected),
            )
        )
    return rows


async def run_reconcile_stocks(settings: Settings, *, apply: bool = False) -> dict:
    odoo = OdooClient(url=settings.odoo_url, db=settings.odoo_db, api_key=settings.odoo_api_key)
    binding_repo = BindingRepository(odoo)
    client = await get_saleor_client(settings)

    warehouse = await stock_adapter.fetch_default_warehouse(odoo)
    if warehouse is None:
        return {"checked": 0, "ok": 0, "drift": 0, "fixed": 0, "rows": [],
                "apply": apply, "errors": ["no stock.warehouse in Odoo"]}
    warehouse_saleor_id = await sm.ensure_warehouse(client, binding_repo, warehouse)

    odoo_levels = await stock_adapter.fetch_all_aggregated_stock(
        odoo, warehouse, safety_buffer=settings.stock_safety_buffer
    )
    saleor_stocks = await sm.list_variant_stocks(client)
    rows = diff_stock(odoo_levels, saleor_stocks, warehouse.slug)
    drift_rows = [r for r in rows if r.drift]

    summary: dict = {
        "checked": len(rows),
        "ok": len(rows) - len(drift_rows),
        "drift": len(drift_rows),
        "fixed": 0,
        "rows": rows,
        "apply": apply,
        "errors": [],
    }

    if apply and drift_rows:
        for r in drift_rows:
            info = saleor_stocks[r.sku]
            try:
                await sm.set_track_inventory(client, info["variant_id"], track=True)
                await sm.update_variant_stock(
                    client, variant_id=info["variant_id"],
                    warehouse_id=warehouse_saleor_id, quantity=r.expected,
                )
                summary["fixed"] += 1
            except Exception as exc:  # noqa: BLE001
                summary["errors"].append(f"{r.sku}: {exc}")
                log.warning("reconcile_fix_failed", sku=r.sku, error=str(exc))

    log.info("stock_reconcile", checked=summary["checked"], drift=summary["drift"],
             fixed=summary["fixed"], apply=apply)
    return summary
