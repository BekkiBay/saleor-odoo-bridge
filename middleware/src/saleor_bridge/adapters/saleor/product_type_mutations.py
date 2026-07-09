"""Singleton ProductType "Generic" (ADR-0012). Get-or-create, кэш в saleor.binding."""

from __future__ import annotations

import structlog

from saleor_bridge.adapters.odoo.binding import BindingRepository
from saleor_bridge.adapters.saleor.common import query_data, run_mutation
from saleor_bridge.adapters.saleor.slug import slugify
from saleor_bridge.saleor.client import SaleorClient

log = structlog.get_logger()

_BINDING_MODEL = "product.type"

_FIND = """
query($search:String!){
  productTypes(first:100, filter:{search:$search}){ edges{ node{ id name } } }
}
"""

_CREATE = """
mutation($input: ProductTypeInput!){
  productTypeCreate(input:$input){
    productType{ id name }
    errors{ field message code }
  }
}
"""


async def ensure_product_type(
    client: SaleorClient,
    binding_repo: BindingRepository,
    name: str,
) -> str:
    """Вернуть Saleor ProductType id, создав при необходимости. Идемпотентно."""
    # 1. binding-кэш
    cached = await binding_repo.find_saleor_id(_BINDING_MODEL, 0)
    if cached:
        return cached

    # 2. поиск по имени в Saleor
    data = await query_data(client, _FIND, {"search": name})
    for edge in data.get("productTypes", {}).get("edges", []):
        node = edge["node"]
        if node["name"] == name:
            await binding_repo.upsert_out(_BINDING_MODEL, node["id"], 0)
            log.info("product_type_found", name=name, saleor_id=node["id"])
            return node["id"]

    # 3. создать
    payload = await run_mutation(
        client,
        _CREATE,
        {"input": {
            "name": name,
            "slug": slugify(name),
            "kind": "NORMAL",
            "hasVariants": False,
            "isShippingRequired": True,
        }},
        "productTypeCreate",
    )
    saleor_id = payload["productType"]["id"]
    await binding_repo.upsert_out(_BINDING_MODEL, saleor_id, 0)
    log.info("product_type_created", name=name, saleor_id=saleor_id)
    return saleor_id
