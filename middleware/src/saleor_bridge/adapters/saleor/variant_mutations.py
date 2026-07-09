"""Saleor ProductVariant mutations. Pure GraphQL; binding/resolution lives in the usecase.

Bulk create generates a set of variants (productVariantBulkCreate, price inline),
single delete handles targeted edits. Attribute input arrives already resolved:
[{id: <attrSaleorId>, dropdownValue: {id: <valueSaleorId>}}].

NB: Saleor ProductVariant does NOT have a `barcode` field (verified on 3.23: "Unknown
field"). Barcode stays in Odoo (source of truth); we don't push it to Saleor
(could be added via metadata if ever needed).
"""

from __future__ import annotations

import structlog

from saleor_bridge.adapters.saleor.common import SaleorError, run_mutation
from saleor_bridge.saleor.client import SaleorClient

log = structlog.get_logger()

_BULK_CREATE = """
mutation($product: ID!, $variants: [ProductVariantBulkCreateInput!]!){
  productVariantBulkCreate(product:$product, variants:$variants){
    results{ productVariant{ id sku } errors{ field message code } }
    errors{ field message code }
  }
}
"""

_DELETE = """
mutation($id: ID!){
  productVariantDelete(id:$id){
    productVariant{ id }
    errors{ field message code }
  }
}
"""


def attribute_input(attr_saleor_id: str, value_saleor_id: str) -> dict:
    """One element of variant.attributes for DROPDOWN (ADR-0027).

    Shape is BulkAttributeValueInput (productVariantBulkCreate): `dropdown`, NOT
    `dropdownValue` (the latter belongs to AttributeValueInput for single create).
    """
    return {"id": attr_saleor_id, "dropdown": {"id": value_saleor_id}}


async def bulk_create_variants(
    client: SaleorClient, *, product_id: str, variants: list[dict]
) -> dict[str, str]:
    """Create a set of variants in a single call. Returns {sku: variant_saleor_id}.

    `variants[i]` = {sku, attributes, channelListings, trackInventory}. Price/availability
    are inline in channelListings (no separate channel-listing call needed).
    """
    body = await client.execute(_BULK_CREATE, {"product": product_id, "variants": variants})
    if body.get("errors"):
        msg = "; ".join(e.get("message", "?") for e in body["errors"])
        raise SaleorError(f"productVariantBulkCreate: top-level error: {msg}")
    payload = (body.get("data") or {}).get("productVariantBulkCreate") or {}
    if payload.get("errors"):
        raise SaleorError(f"productVariantBulkCreate: {payload['errors']}")
    out: dict[str, str] = {}
    for res in payload.get("results", []):
        if res.get("errors"):
            raise SaleorError(f"productVariantBulkCreate item errors: {res['errors']}")
        v = res["productVariant"]
        out[v["sku"]] = v["id"]
    return out


async def delete_variant(client: SaleorClient, variant_id: str) -> None:
    """Delete a variant. Idempotent: already-deleted (NOT_FOUND) is not an error."""
    try:
        await run_mutation(client, _DELETE, {"id": variant_id}, "productVariantDelete")
    except SaleorError as exc:
        msg = str(exc).lower()
        if "not_found" in msg or "could not" in msg or "does not exist" in msg or "not found" in msg:
            log.info("variant_delete_already_gone", variant_id=variant_id)
            return
        raise
    log.info("variant_deleted", variant_id=variant_id)
