"""Usecase: sync customer Saleor → Odoo. Platform-independent (operates on domain.Customer)."""

from __future__ import annotations

import structlog

from saleor_bridge.adapters.odoo import partner as partner_adapter
from saleor_bridge.adapters.odoo.binding import BindingRepository
from saleor_bridge.domain.customer import Customer
from saleor_bridge.odoo.client import OdooClient
from saleor_bridge.usecases.result import SyncResult

log = structlog.get_logger()

_PARTNER = "res.partner"


async def sync_customer_to_odoo(
    customer: Customer,
    odoo: OdooClient,
    binding_repo: BindingRepository,
) -> SyncResult:
    """Upsert customer:
    1. lookup binding by saleor_id
    2. else lookup res.partner by email
    3. else create
    4. update fields + addresses
    5. upsert binding
    """
    # 1. binding
    odoo_id = await binding_repo.find_odoo_id(_PARTNER, customer.external_id)

    # 2. email fallback
    if odoo_id is None:
        odoo_id = await partner_adapter.find_partner_id(odoo, str(customer.email))

    # 3-4. upsert
    partner_id = await partner_adapter.upsert_partner(odoo, customer, existing_id=odoo_id)

    # 5. binding
    await binding_repo.upsert(_PARTNER, customer.external_id, partner_id, direction="in")

    log.info(
        "customer_synced",
        saleor_id=customer.external_id,
        odoo_partner_id=partner_id,
        created=odoo_id is None,
    )
    return SyncResult(ok=True, odoo_id=partner_id, message="customer synced")
