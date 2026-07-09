"""Usecase: push the canonical fulfillment_status (computed in Odoo) → Saleor order
metadata (spec 2026-06-22). The mapping lives in Odoo; the middleware reads the
field and writes it verbatim to metadata. Orders without a Saleor binding
(created manually in Odoo) are skipped.
"""
from __future__ import annotations

import structlog

from saleor_bridge.adapters.odoo import sale_order as so_adapter
from saleor_bridge.adapters.odoo.binding import BindingRepository
from saleor_bridge.adapters.saleor import order_mutations as om
from saleor_bridge.odoo.client import OdooClient
from saleor_bridge.saleor.client import SaleorClient
from saleor_bridge.usecases.result import SyncResult

log = structlog.get_logger()

_SO = "sale.order"


async def sync_canonical_status_to_saleor(
    odoo_order_id: int,
    client: SaleorClient,
    odoo: OdooClient,
    binding_repo: BindingRepository,
) -> SyncResult:
    status = await so_adapter.fetch_fulfillment_status(odoo, odoo_order_id)
    if not status:
        return SyncResult(ok=True, odoo_id=odoo_order_id, message="no fulfillment_status, skipped")

    saleor_id = await binding_repo.find_saleor_id(_SO, odoo_order_id)
    if saleor_id is None:
        log.info("canonical_status_no_binding", odoo_id=odoo_order_id, status=status)
        return SyncResult(ok=True, odoo_id=odoo_order_id, message="no binding, skipped")

    res = await om.update_order_metadata(client, saleor_id, {"fulfillment_status": status})
    if res.ok:
        await binding_repo.touch_out(_SO, odoo_order_id)
    log.info("canonical_status_synced", odoo_id=odoo_order_id, status=status, ok=res.ok)
    return SyncResult(ok=res.ok, odoo_id=odoo_order_id, message=f"fulfillment_status={status}")
