"""Usecase: sync order Saleor → Odoo. Event-driven status (ADR-0005)."""

from __future__ import annotations

import structlog

from saleor_bridge.adapters.odoo import partner as partner_adapter
from saleor_bridge.adapters.odoo import sale_order as so_adapter
from saleor_bridge.adapters.odoo.binding import BindingRepository
from saleor_bridge.config import get_settings
from saleor_bridge.domain.customer import Customer
from saleor_bridge.domain.enums import OrderStatus
from saleor_bridge.domain.order import Order
from saleor_bridge.odoo.client import OdooClient
from saleor_bridge.usecases.result import SyncResult
from saleor_bridge.usecases.sync_customer import sync_customer_to_odoo

log = structlog.get_logger()

_SO = "sale.order"


class OrderNotYetCreated(RuntimeError):
    """ORDER_PAID/CANCELLED пришёл раньше ORDER_CREATED — retryable."""


async def _check_total_guard(
    order: Order,
    odoo: OdooClient,
    binding_repo: BindingRepository,
    tolerance: int,
    warnings: list[str],
    order_id: int | None = None,
) -> bool:
    """Verify the created Odoo order total matches Saleor. On mismatch: mark the
    binding 'diverged' + warn (do NOT raise — deterministic). Returns match bool."""
    oid = order_id if order_id is not None else await so_adapter.find_order_id(odoo, order)
    odoo_total = await so_adapter.fetch_amount_total(odoo, oid)
    if so_adapter.order_totals_match(odoo_total, order.total, tolerance):
        return True
    msg = f"total mismatch: odoo={odoo_total} saleor={order.total}"
    log.error("order_total_diverged", order_id=oid, ref=order.client_order_ref,
              odoo_total=str(odoo_total), saleor_total=str(order.total))
    warnings.append(msg)
    await binding_repo.upsert(_SO, order.external_id, oid, direction="in",
                              state="diverged", error=msg)
    return False


def _customer_from_order(order: Order) -> Customer:
    """Собрать domain.Customer из order payload (для guest или logged-in)."""
    billing = order.billing_address
    first = billing.first_name if billing else ""
    last = billing.last_name if billing else ""
    return Customer(
        external_id=order.customer_external_id or f"email:{order.customer_email}",
        email=order.customer_email,
        first_name=first or None,
        last_name=last or None,
        phone=(billing.phone if billing else None),
        default_billing_address=order.billing_address,
        default_shipping_address=order.shipping_address,
    )


async def sync_order_to_odoo(
    order: Order,
    odoo: OdooClient,
    binding_repo: BindingRepository,
) -> SyncResult:
    warnings: list[str] = []

    if order.status == OrderStatus.DRAFT:
        return await _handle_created(order, odoo, binding_repo, warnings)
    if order.status == OrderStatus.CONFIRMED:
        return await _handle_paid(order, odoo, binding_repo)
    if order.status == OrderStatus.CANCELLED:
        return await _handle_cancelled(order, odoo, binding_repo)
    return SyncResult(ok=False, message=f"unknown status {order.status}")


async def _handle_created(
    order: Order, odoo: OdooClient, binding_repo: BindingRepository, warnings: list[str]
) -> SyncResult:
    # Idempotency: если sale.order уже есть по client_order_ref — skip create.
    existing = await so_adapter.find_order_id(odoo, order)
    if existing:
        log.info("order_already_exists", order_id=existing, ref=order.client_order_ref)
        await binding_repo.upsert(_SO, order.external_id, existing, direction="in")
        return SyncResult(ok=True, odoo_id=existing, message="order already exists")

    # 1. ensure customer
    customer = _customer_from_order(order)
    cust_result = await sync_customer_to_odoo(customer, odoo, binding_repo)
    partner_id = cust_result.odoo_id
    if partner_id is None:
        return SyncResult(ok=False, message="customer sync failed")

    invoice_id = await partner_adapter.get_child_address_id(odoo, partner_id, "invoice")
    shipping_id = await partner_adapter.get_child_address_id(odoo, partner_id, "delivery")

    # 2. create draft order
    settings = get_settings()
    order_id = await so_adapter.create_draft_order(
        odoo, order, partner_id, invoice_id, shipping_id,
        shipping_sku=settings.odoo_shipping_sku,
    )

    tolerance = settings.order_total_tolerance
    if not await _check_total_guard(order, odoo, binding_repo, tolerance, warnings, order_id):
        return SyncResult(ok=True, odoo_id=order_id, message="order created (diverged)", warnings=warnings)

    await binding_repo.upsert(_SO, order.external_id, order_id, direction="in")
    log.info("order_created", order_id=order_id, ref=order.client_order_ref)
    return SyncResult(ok=True, odoo_id=order_id, message="order draft created", warnings=warnings)


async def _resolve_order_id(order: Order, odoo: OdooClient, binding_repo: BindingRepository) -> int:
    odoo_id = await binding_repo.find_odoo_id(_SO, order.external_id)
    if odoo_id is None:
        odoo_id = await so_adapter.find_order_id(odoo, order)
    if odoo_id is None:
        # Race: paid/cancel пришёл раньше created. Retryable.
        raise OrderNotYetCreated(
            f"sale.order for {order.client_order_ref} not found yet"
        )
    return odoo_id


async def _handle_paid(order: Order, odoo: OdooClient, binding_repo: BindingRepository) -> SyncResult:
    order_id = await _resolve_order_id(order, odoo, binding_repo)
    await so_adapter.confirm_order(odoo, order_id)
    await binding_repo.upsert(_SO, order.external_id, order_id, direction="in")
    log.info("order_confirmed", order_id=order_id, ref=order.client_order_ref)
    return SyncResult(ok=True, odoo_id=order_id, message="order confirmed")


async def _handle_cancelled(
    order: Order, odoo: OdooClient, binding_repo: BindingRepository
) -> SyncResult:
    order_id = await _resolve_order_id(order, odoo, binding_repo)
    await so_adapter.cancel_order(odoo, order_id)
    await binding_repo.upsert(_SO, order.external_id, order_id, direction="in")
    log.info("order_cancelled", order_id=order_id, ref=order.client_order_ref)
    return SyncResult(ok=True, odoo_id=order_id, message="order cancelled")
