"""Usecase: order lifecycle Odoo → Saleor (Phase 3.4, ADR-0019).

Worker перечитывает состояние из Odoo и решает мутацию. Binding sale.order
(odoo_id ↔ Saleor order id) создаёт Phase 3.1. Заказы без binding (созданные
вручную в Odoo) пропускаем — это не Saleor-заказы.
"""

from __future__ import annotations

import structlog

from saleor_bridge.adapters.odoo import sale_order as so_adapter
from saleor_bridge.adapters.odoo import stock as stock_adapter
from saleor_bridge.adapters.odoo import stock_picking as picking_adapter
from saleor_bridge.adapters.odoo.binding import BindingRepository
from saleor_bridge.adapters.saleor import order_mutations as om
from saleor_bridge.adapters.saleor import stock_mutations as sm
from saleor_bridge.odoo.client import OdooClient
from saleor_bridge.saleor.client import SaleorClient
from saleor_bridge.usecases.result import SyncResult

log = structlog.get_logger()

_SO = "sale.order"


def decide_order_action(state: str | None) -> str | None:
    """Odoo sale.order.state → действие (pure, тестируемо). ADR-0019."""
    if state == "sale":
        return "confirm"
    if state == "cancel":
        return "cancel"
    return None  # draft / done (locked) → no-op


async def sync_order_state_to_saleor(
    odoo_order_id: int,
    client: SaleorClient,
    odoo: OdooClient,
    binding_repo: BindingRepository,
) -> SyncResult:
    info = await so_adapter.fetch_state(odoo, odoo_order_id)
    if info is None:
        return SyncResult(ok=False, message=f"sale.order {odoo_order_id} not found")

    action = decide_order_action(info.get("state"))
    if action is None:
        return SyncResult(ok=True, odoo_id=odoo_order_id, message=f"state {info.get('state')} → no-op")

    saleor_id = await binding_repo.find_saleor_id(_SO, odoo_order_id)
    if saleor_id is None:
        log.info("order_state_no_binding", odoo_id=odoo_order_id, state=info.get("state"))
        return SyncResult(ok=True, odoo_id=odoo_order_id, message="no saleor binding, skipped")

    res = await om.confirm_order(client, saleor_id) if action == "confirm" \
        else await om.cancel_order(client, saleor_id)
    if res.ok:
        await binding_repo.touch_out(_SO, odoo_order_id)
    log.info("order_state_synced", odoo_id=odoo_order_id, action=action, ok=res.ok, msg=res.message)
    return SyncResult(ok=res.ok, odoo_id=odoo_order_id, message=res.message)


async def sync_picking_to_saleor(
    odoo_picking_id: int,
    client: SaleorClient,
    odoo: OdooClient,
    binding_repo: BindingRepository,
    *,
    notify: bool = True,
) -> SyncResult:
    pick = await picking_adapter.fetch_picking_with_lines(odoo, odoo_picking_id)
    if pick is None:
        return SyncResult(ok=False, message=f"picking {odoo_picking_id} not found")
    if pick["state"] != "done":
        return SyncResult(ok=True, message=f"picking state {pick['state']} → no-op")

    so_id = pick["sale_order_id"]
    if not so_id:
        return SyncResult(ok=True, message="picking has no sale order, skipped")
    saleor_id = await binding_repo.find_saleor_id(_SO, so_id)
    if saleor_id is None:
        log.info("picking_no_order_binding", picking=odoo_picking_id, sale_order=so_id)
        return SyncResult(ok=True, message="no saleor binding for order, skipped")
    if not pick["sku_qty"]:
        return SyncResult(ok=True, message="no shipped lines, skipped")

    warehouse = await stock_adapter.fetch_default_warehouse(odoo)
    if warehouse is None:
        return SyncResult(ok=False, message="no stock.warehouse in Odoo")
    warehouse_saleor_id = await sm.ensure_warehouse(client, binding_repo, warehouse)

    res = await om.fulfill_order(
        client, saleor_id,
        sku_qty=pick["sku_qty"], warehouse_id=warehouse_saleor_id,
        tracking_number=pick["tracking"], notify=notify,
    )
    if res.ok:
        await binding_repo.touch_out(_SO, so_id)
    log.info("picking_synced", picking=odoo_picking_id, sale_order=so_id, ok=res.ok, msg=res.message)
    return SyncResult(ok=res.ok, odoo_id=so_id, message=res.message)
