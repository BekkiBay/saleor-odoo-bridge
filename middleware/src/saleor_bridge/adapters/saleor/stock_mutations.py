"""Saleor Warehouse + Stock mutations. Pure GraphQL; binding lives in the usecase.

- ensure_warehouse: get-or-create, reuses an existing Saleor warehouse bound
  to the channel (ADR-0015) so stock lands in quantityAvailable.
- update_variant_stock: productVariantStocksUpdate (upsert of stock per warehouse).
- set_track_inventory: flip trackInventory=True (previously left False, ADR-0014;
  "out of stock" at qty=0 requires True, ADR-0010).
"""

from __future__ import annotations

import structlog

from saleor_bridge.adapters.odoo.binding import BindingRepository
from saleor_bridge.adapters.saleor.common import query_data, run_mutation
from saleor_bridge.domain.stock import Warehouse
from saleor_bridge.saleor.client import SaleorClient

log = structlog.get_logger()

_WH_MODEL = "stock.warehouse"

_LIST_WAREHOUSES = """
query{ warehouses(first:100){ edges{ node{ id slug name } } } }
"""

_CREATE_WAREHOUSE = """
mutation($input: WarehouseCreateInput!){
  createWarehouse(input:$input){
    warehouse{ id slug name }
    errors{ field message code }
  }
}
"""

_STOCKS_UPDATE = """
mutation($variantId: ID!, $stocks: [StockInput!]!){
  productVariantStocksUpdate(variantId:$variantId, stocks:$stocks){
    productVariant{ id }
    errors{ field message code }
  }
}
"""

_VARIANT_UPDATE = """
mutation($id: ID!, $input: ProductVariantInput!){
  productVariantUpdate(id:$id, input:$input){
    productVariant{ id trackInventory }
    errors{ field message code }
  }
}
"""

_VARIANT_STOCK = """
query($id: ID!){
  productVariant(id:$id){
    id sku trackInventory
    stocks{ quantity warehouse{ id slug } }
  }
}
"""

_LIST_VARIANT_STOCKS = """
query($after: String){
  productVariants(first:100, after:$after){
    edges{ node{ id sku trackInventory stocks{ quantity warehouse{ id slug } } } }
    pageInfo{ hasNextPage endCursor }
  }
}
"""


async def ensure_warehouse(
    client: SaleorClient, binding_repo: BindingRepository, warehouse: Warehouse
) -> str:
    """Return the Saleor warehouse id for an Odoo warehouse. Get-or-create (ADR-0015).

    Priority: binding → existing Saleor warehouse (bound to the channel) → create.
    """
    odoo_id = int(warehouse.external_id)
    bound = await binding_repo.find_saleor_id(_WH_MODEL, odoo_id)
    if bound:
        return bound

    data = await query_data(client, _LIST_WAREHOUSES)
    edges = data.get("warehouses", {}).get("edges", [])
    if edges:
        # Reuse the existing (default) warehouse — it's already in the channel's
        # shipping zone, so stock will land in quantityAvailable right away.
        saleor_id = edges[0]["node"]["id"]
        await binding_repo.upsert_out(_WH_MODEL, saleor_id, odoo_id, state="synced")
        log.info("warehouse_bound_existing", odoo_id=odoo_id, saleor_id=saleor_id,
                 slug=edges[0]["node"]["slug"])
        return saleor_id

    payload = await run_mutation(
        client, _CREATE_WAREHOUSE,
        {"input": {"name": warehouse.name, "slug": warehouse.slug}},
        "createWarehouse",
    )
    saleor_id = payload["warehouse"]["id"]
    await binding_repo.upsert_out(_WH_MODEL, saleor_id, odoo_id, state="synced")
    log.warning("warehouse_created_new", odoo_id=odoo_id, saleor_id=saleor_id, slug=warehouse.slug,
                note="new warehouse is not bound to the channel's shipping zone — check quantityAvailable")
    return saleor_id


async def set_track_inventory(client: SaleorClient, variant_id: str, *, track: bool) -> None:
    await run_mutation(
        client, _VARIANT_UPDATE,
        {"id": variant_id, "input": {"trackInventory": track}},
        "productVariantUpdate",
    )


async def update_variant_stock(
    client: SaleorClient, *, variant_id: str, warehouse_id: str, quantity: int
) -> None:
    """productVariantStocksUpdate — upsert of the warehouse stock (creates/updates Stock)."""
    await run_mutation(
        client, _STOCKS_UPDATE,
        {"variantId": variant_id, "stocks": [{"warehouse": warehouse_id, "quantity": quantity}]},
        "productVariantStocksUpdate",
    )


async def fetch_variant_stock(client: SaleorClient, variant_id: str) -> dict | None:
    """Current state of the variant: sku, trackInventory, stocks[]."""
    data = await query_data(client, _VARIANT_STOCK, {"id": variant_id})
    return data.get("productVariant")


async def list_variant_stocks(client: SaleorClient) -> dict[str, dict]:
    """All Saleor variants → {sku: {variant_id, total, track}} (for reconcile).

    `total` = sum across warehouses (single-warehouse MVP, ADR-0015 → one Stock).
    """
    out: dict[str, dict] = {}
    after = None
    while True:
        data = await query_data(client, _LIST_VARIANT_STOCKS, {"after": after})
        conn = data["productVariants"]
        for edge in conn["edges"]:
            node = edge["node"]
            sku = node.get("sku")
            if not sku:
                continue
            total = sum(int(s["quantity"]) for s in node.get("stocks", []))
            out[sku] = {
                "variant_id": node["id"],
                "total": total,
                "track": node.get("trackInventory"),
            }
        if not conn["pageInfo"]["hasNextPage"]:
            break
        after = conn["pageInfo"]["endCursor"]
    return out
