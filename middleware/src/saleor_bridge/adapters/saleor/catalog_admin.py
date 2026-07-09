"""Catalog admin operations: resolve channel + wipe (ADR-0013 `wipe` command)."""

from __future__ import annotations

import structlog

from saleor_bridge.adapters.saleor.common import query_data, run_mutation
from saleor_bridge.saleor.client import SaleorClient

log = structlog.get_logger()

_CHANNEL = """
query($slug: String!){ channel(slug:$slug){ id slug currencyCode } }
"""

_LIST_PRODUCTS = """
query($after: String){
  products(first:100, after:$after){
    edges{ node{ id } }
    pageInfo{ hasNextPage endCursor }
  }
}
"""

_LIST_ROOT_CATEGORIES = """
query($after: String){
  categories(first:100, level:0, after:$after){
    edges{ node{ id name } }
    pageInfo{ hasNextPage endCursor }
  }
}
"""

_BULK_DELETE_PRODUCTS = """
mutation($ids: [ID!]!){ productBulkDelete(ids:$ids){ count errors{ message } } }
"""

_DELETE_CATEGORY = """
mutation($id: ID!){ categoryDelete(id:$id){ errors{ message } } }
"""


async def resolve_channel(client: SaleorClient, slug: str) -> dict:
    """Return {id, slug, currencyCode}. Raises if the channel is not found."""
    data = await query_data(client, _CHANNEL, {"slug": slug})
    ch = data.get("channel")
    if not ch:
        raise RuntimeError(f"Saleor channel '{slug}' not found")
    return ch


async def _page_ids(client: SaleorClient, query: str, root: str) -> list[str]:
    ids: list[str] = []
    after = None
    while True:
        data = await query_data(client, query, {"after": after})
        conn = data[root]
        ids.extend(e["node"]["id"] for e in conn["edges"])
        if not conn["pageInfo"]["hasNextPage"]:
            break
        after = conn["pageInfo"]["endCursor"]
    return ids


async def wipe_catalog(client: SaleorClient) -> dict:
    """Delete ALL products + root categories (cascades the whole tree). DESTRUCTIVE."""
    product_ids = await _page_ids(client, _LIST_PRODUCTS, "products")
    deleted_products = 0
    for i in range(0, len(product_ids), 100):
        batch = product_ids[i : i + 100]
        payload = await run_mutation(client, _BULK_DELETE_PRODUCTS, {"ids": batch}, "productBulkDelete")
        deleted_products += payload.get("count", 0)

    root_ids = await _page_ids(client, _LIST_ROOT_CATEGORIES, "categories")
    deleted_categories = 0
    for cid in root_ids:
        await run_mutation(client, _DELETE_CATEGORY, {"id": cid}, "categoryDelete")
        deleted_categories += 1

    log.info("catalog_wiped", products=deleted_products, root_categories=deleted_categories)
    return {"products": deleted_products, "root_categories": deleted_categories}
