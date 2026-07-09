"""Usecase: sync product.attribute / .value Odoo → Saleor (ADR-0023/0027).

Guarantees: the global Saleor Attribute + all its values exist, and the attribute
is enabled as a VARIANT attribute on the "Generic" ProductType (hasVariants=True).
An event on .value delegates to syncing the parent attribute (ensures all values).
Idempotent via saleor.binding.
"""

from __future__ import annotations

import structlog

from saleor_bridge.adapters.odoo import attribute as attr_adapter
from saleor_bridge.adapters.odoo.binding import BindingRepository
from saleor_bridge.adapters.saleor import attribute_mutations as am
from saleor_bridge.odoo.client import OdooClient
from saleor_bridge.saleor.client import SaleorClient
from saleor_bridge.usecases.result import SyncResult

log = structlog.get_logger()

_ATTR = "product.attribute"
_VALUE = "product.attribute.value"


async def sync_attribute_to_saleor(
    odoo_id: int,
    client: SaleorClient,
    odoo: OdooClient,
    binding_repo: BindingRepository,
    *,
    product_type_id: str,
    model: str = _ATTR,
) -> SyncResult:
    # Event on a value → sync the parent attribute entirely (it ensures all values).
    if model == _VALUE:
        data = await attr_adapter.fetch_attribute_value(odoo, odoo_id)
        if data is None or data["attribute_id"] is None:
            return SyncResult(ok=False, message=f"attribute.value {odoo_id} not found")
        return await sync_attribute_to_saleor(
            data["attribute_id"], client, odoo, binding_repo,
            product_type_id=product_type_id, model=_ATTR,
        )

    attribute = await attr_adapter.fetch_attribute(odoo, odoo_id)
    if attribute is None:
        # no_variant attribute (material/composition) — product-level, not currently synced. Not an error.
        log.info("attribute_skipped_no_variant", odoo_id=odoo_id)
        return SyncResult(ok=True, odoo_id=odoo_id, message="no_variant attribute skipped")

    attr_saleor_id = await am.ensure_attribute(client, binding_repo, attribute)
    for value in attribute.values:
        await am.ensure_attribute_value(client, binding_repo, attr_saleor_id, value)

    # variant attributes require hasVariants=True on the ProductType (ADR-0023).
    await am.ensure_product_type_has_variants(client, product_type_id)
    await am.assign_attribute_to_product_type(client, attr_saleor_id, product_type_id)

    log.info("attribute_synced", odoo_id=odoo_id, name=attribute.name,
             saleor_id=attr_saleor_id, values=len(attribute.values))
    return SyncResult(ok=True, odoo_id=odoo_id, message=f"attribute synced ({len(attribute.values)} values)")
