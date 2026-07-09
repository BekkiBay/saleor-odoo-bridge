"""Usecase: sync stock for a single product.product from Odoo → Saleor.

Flow (ADR-0015/0016/0017):
1. product.product → template_id → catalog-binding (Saleor product). Missing binding →
   CatalogBindingMissing (race with catalog-sync) → arq retry.
2. Saleor product → variants[0].id.
3. ensure default warehouse (get-or-create, ADR-0015).
4. aggregate stock from Odoo + safety buffer (ADR-0016) → push productVariantStocksUpdate.
5. trackInventory=True (so qty=0 = "out of stock", ADR-0010).
6. touch catalog-binding.last_sync_out.
"""

from __future__ import annotations

import structlog

from saleor_bridge.adapters.odoo import stock as stock_adapter
from saleor_bridge.adapters.odoo.binding import BindingRepository
from saleor_bridge.adapters.saleor import product_mutations as pm
from saleor_bridge.adapters.saleor import stock_mutations as sm
from saleor_bridge.odoo.client import OdooClient
from saleor_bridge.saleor.client import SaleorClient
from saleor_bridge.usecases.result import SyncResult

log = structlog.get_logger()

_TMPL = "product.template"
_VARIANT = "product.product"


class CatalogBindingMissing(RuntimeError):
    """No catalog-binding for the variant — the catalog hasn't been synced yet (a race).

    Raised so the worker (_guard) retries with backoff: catalog-sync will most
    likely have synced the product by the next attempt. Bulk-seed catches this as a skip.
    """


async def sync_stock_to_saleor(
    pp_id: int,
    client: SaleorClient,
    odoo: OdooClient,
    binding_repo: BindingRepository,
    *,
    safety_buffer: int,
) -> SyncResult:
    ref = await stock_adapter.fetch_variant_ref(odoo, pp_id)
    if ref is None or ref["template_id"] is None:
        return SyncResult(ok=False, message=f"variant {pp_id} not found in Odoo")
    template_id = ref["template_id"]

    saleor_product_id = await binding_repo.find_saleor_id(_TMPL, template_id)
    if saleor_product_id is None:
        raise CatalogBindingMissing(
            f"no product.template binding for tmpl {template_id} (variant {pp_id})"
        )

    # Resolve the SPECIFIC variant (multi-variant). Priority:
    # binding (product.product) → SKU-match → single variant (single-variant case).
    variant_id = await binding_repo.find_saleor_id(_VARIANT, pp_id)
    if variant_id is None:
        state = await pm.fetch_product_state(client, saleor_product_id)
        variants = (state or {}).get("variants") or []
        if not variants:
            raise CatalogBindingMissing(
                f"no Saleor variant for product {saleor_product_id} (tmpl {template_id})"
            )
        match = [v for v in variants if v.get("sku") == ref["sku"]]
        if match:
            variant_id = match[0]["id"]
        elif len(variants) == 1:
            variant_id = variants[0]["id"]
        else:
            raise CatalogBindingMissing(
                f"no variant binding for pp {pp_id} among {len(variants)} variants (sku={ref['sku']})"
            )

    warehouse = await stock_adapter.fetch_default_warehouse(odoo)
    if warehouse is None:
        return SyncResult(ok=False, message="no stock.warehouse in Odoo")
    warehouse_saleor_id = await sm.ensure_warehouse(client, binding_repo, warehouse)

    levels = await stock_adapter.fetch_aggregated_stock(
        odoo, pp_id, warehouse, safety_buffer=safety_buffer
    )

    # trackInventory=True → Saleor shows "out of stock" at zero stock (ADR-0010).
    await sm.set_track_inventory(client, variant_id, track=True)
    for level in levels:
        await sm.update_variant_stock(
            client, variant_id=variant_id,
            warehouse_id=warehouse_saleor_id, quantity=level.display_quantity,
        )

    await binding_repo.touch_out(_TMPL, template_id)
    raw = levels[0].raw_quantity if levels else 0
    pushed = levels[0].display_quantity if levels else 0
    log.info("stock_synced", pp_id=pp_id, tmpl=template_id, sku=ref["sku"], raw=raw, pushed=pushed)
    return SyncResult(ok=True, odoo_id=template_id, message=f"stock synced raw={raw} pushed={pushed}")
