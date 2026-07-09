"""Saleor Attribute / AttributeValue mutations. Pure GraphQL; binding lives in the usecase.

ADR-0023: all attributes are variant attributes of the single "Generic" ProductType.
ADR-0027: only inputType DROPDOWN, type PRODUCT, valueRequired=false (single-variant
products hold variants without attribute values).
"""

from __future__ import annotations

import structlog

from saleor_bridge.adapters.odoo.binding import BindingRepository
from saleor_bridge.adapters.saleor.common import SaleorError, query_data, run_mutation
from saleor_bridge.adapters.saleor.slug import slugify
from saleor_bridge.domain.variants import Attribute, AttributeValue
from saleor_bridge.saleor.client import SaleorClient

log = structlog.get_logger()

_ATTR_MODEL = "product.attribute"
_VALUE_MODEL = "product.attribute.value"

_FIND_ATTR = """
query($search: String!){
  attributes(first:100, filter:{search:$search}){ edges{ node{ id name slug } } }
}
"""

_CREATE_ATTR = """
mutation($input: AttributeCreateInput!){
  attributeCreate(input:$input){
    attribute{ id name slug }
    errors{ field message code }
  }
}
"""

_ATTR_CHOICES = """
query($id: ID!){
  attribute(id:$id){ id choices(first:100){ edges{ node{ id name } } } }
}
"""

_CREATE_VALUE = """
mutation($attribute: ID!, $input: AttributeValueCreateInput!){
  attributeValueCreate(attribute:$attribute, input:$input){
    attributeValue{ id name slug }
    errors{ field message code }
  }
}
"""

_PRODUCT_TYPE_ATTRS = """
query($id: ID!){
  productType(id:$id){ id hasVariants variantAttributes{ id } }
}
"""

_ASSIGN_ATTR = """
mutation($productTypeId: ID!, $operations: [ProductAttributeAssignInput!]!){
  productAttributeAssign(productTypeId:$productTypeId, operations:$operations){
    productType{ id }
    errors{ field message code }
  }
}
"""

_UPDATE_PRODUCT_TYPE = """
mutation($id: ID!, $input: ProductTypeInput!){
  productTypeUpdate(id:$id, input:$input){
    productType{ id hasVariants }
    errors{ field message code }
  }
}
"""


async def ensure_attribute(
    client: SaleorClient, binding_repo: BindingRepository, attribute: Attribute
) -> str:
    """Saleor Attribute id for an Odoo product.attribute. Get-or-create, idempotent."""
    odoo_id = int(attribute.external_id)
    cached = await binding_repo.find_saleor_id(_ATTR_MODEL, odoo_id)
    if cached:
        return cached

    data = await query_data(client, _FIND_ATTR, {"search": attribute.name})
    for edge in data.get("attributes", {}).get("edges", []):
        if edge["node"]["name"] == attribute.name:
            saleor_id = edge["node"]["id"]
            await binding_repo.upsert_out(_ATTR_MODEL, saleor_id, odoo_id)
            log.info("attribute_found", name=attribute.name, saleor_id=saleor_id)
            return saleor_id

    # slug is globally unique; Saleor demo data may already occupy the base slug —
    # on collision we retry with an odoo_id suffix (deterministically unique).
    base_slug = slugify(attribute.name)
    base_input = {
        "name": attribute.name,
        "type": "PRODUCT_TYPE",  # AttributeTypeEnum: PRODUCT_TYPE | PAGE_TYPE
        "inputType": attribute.input_type,
        "valueRequired": False,
    }
    for attempt_slug in (base_slug, f"{base_slug}-{odoo_id}"):
        try:
            payload = await run_mutation(
                client, _CREATE_ATTR, {"input": {**base_input, "slug": attempt_slug}}, "attributeCreate"
            )
            saleor_id = payload["attribute"]["id"]
            await binding_repo.upsert_out(_ATTR_MODEL, saleor_id, odoo_id)
            log.info("attribute_created", name=attribute.name, saleor_id=saleor_id, slug=attempt_slug)
            return saleor_id
        except SaleorError as exc:
            if getattr(exc, "slug_conflict", False) and attempt_slug == base_slug:
                log.warning("attribute_slug_conflict_retry", slug=base_slug)
                continue
            raise
    raise SaleorError(f"attribute slug exhausted retries: {base_slug}")  # pragma: no cover


async def ensure_attribute_value(
    client: SaleorClient,
    binding_repo: BindingRepository,
    attribute_saleor_id: str,
    value: AttributeValue,
) -> str:
    """Saleor AttributeValue id for an Odoo product.attribute.value. Get-or-create."""
    odoo_id = int(value.external_id)
    cached = await binding_repo.find_saleor_id(_VALUE_MODEL, odoo_id)
    if cached:
        return cached

    data = await query_data(client, _ATTR_CHOICES, {"id": attribute_saleor_id})
    choices = (data.get("attribute") or {}).get("choices", {}).get("edges", [])
    for edge in choices:
        if edge["node"]["name"] == value.name:
            saleor_id = edge["node"]["id"]
            await binding_repo.upsert_out(_VALUE_MODEL, saleor_id, odoo_id)
            log.info("attribute_value_found", name=value.name, saleor_id=saleor_id)
            return saleor_id

    payload = await run_mutation(
        client, _CREATE_VALUE,
        {"attribute": attribute_saleor_id, "input": {"name": value.name}},
        "attributeValueCreate",
    )
    saleor_id = payload["attributeValue"]["id"]
    await binding_repo.upsert_out(_VALUE_MODEL, saleor_id, odoo_id)
    log.info("attribute_value_created", name=value.name, saleor_id=saleor_id)
    return saleor_id


async def ensure_product_type_has_variants(client: SaleorClient, product_type_id: str) -> None:
    """Enable hasVariants on the "Generic" ProductType (needed for variant attributes)."""
    data = await query_data(client, _PRODUCT_TYPE_ATTRS, {"id": product_type_id})
    if (data.get("productType") or {}).get("hasVariants"):
        return
    await run_mutation(
        client, _UPDATE_PRODUCT_TYPE,
        {"id": product_type_id, "input": {"hasVariants": True}},
        "productTypeUpdate",
    )
    log.info("product_type_has_variants_enabled", product_type_id=product_type_id)


async def assign_attribute_to_product_type(
    client: SaleorClient, attribute_saleor_id: str, product_type_id: str
) -> None:
    """Attach an attribute to a ProductType as a VARIANT attribute. Idempotent (skips if already assigned)."""
    data = await query_data(client, _PRODUCT_TYPE_ATTRS, {"id": product_type_id})
    assigned = {a["id"] for a in (data.get("productType") or {}).get("variantAttributes", [])}
    if attribute_saleor_id in assigned:
        return
    await run_mutation(
        client, _ASSIGN_ATTR,
        {"productTypeId": product_type_id, "operations": [
            {"id": attribute_saleor_id, "type": "VARIANT", "variantSelection": True}
        ]},
        "productAttributeAssign",
    )
    log.info("attribute_assigned", attribute=attribute_saleor_id, product_type=product_type_id)
