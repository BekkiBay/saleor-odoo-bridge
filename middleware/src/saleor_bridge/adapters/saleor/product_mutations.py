"""Saleor Product/Variant/ChannelListing мутации. Pure GraphQL; binding — в usecase.

Phase 3.2: 1 product + 1 dummy variant (ADR-0012), без stock (ADR-0014).
"""

from __future__ import annotations

import json

import structlog

from saleor_bridge.adapters.saleor.common import SaleorError, query_data, run_mutation
from saleor_bridge.adapters.saleor.slug import with_suffix
from saleor_bridge.saleor.client import SaleorClient

log = structlog.get_logger()

_MAX_SLUG_RETRY = 3

# Saleor description — EditorJS JSON (JSONString scalar).
def description_to_editorjs(text: str | None) -> str | None:
    if not text:
        return None
    return json.dumps({"blocks": [{"type": "paragraph", "data": {"text": text}}]})


def metadata_list(meta: dict[str, str]) -> list[dict]:
    return [{"key": k, "value": v} for k, v in meta.items()]


_CREATE_PRODUCT = """
mutation($input: ProductCreateInput!){
  productCreate(input:$input){
    product{ id slug name }
    errors{ field message code }
  }
}
"""

_UPDATE_PRODUCT = """
mutation($id: ID!, $input: ProductInput!){
  productUpdate(id:$id, input:$input){
    product{ id slug name }
    errors{ field message code }
  }
}
"""

_CREATE_VARIANT = """
mutation($input: ProductVariantCreateInput!){
  productVariantCreate(input:$input){
    productVariant{ id sku }
    errors{ field message code }
  }
}
"""

_PUBLISH = """
mutation($id: ID!, $input: ProductChannelListingUpdateInput!){
  productChannelListingUpdate(id:$id, input:$input){
    errors{ field message code }
  }
}
"""

_SET_PRICE = """
mutation($id: ID!, $input: [ProductVariantChannelListingAddInput!]!){
  productVariantChannelListingUpdate(id:$id, input:$input){
    errors{ field message code }
  }
}
"""

_PRODUCT_STATE = """
query($id: ID!){
  product(id:$id){
    id name
    metafields
    variants{ id sku }
  }
}
"""


async def create_product(
    client: SaleorClient,
    *,
    name: str,
    slug: str,
    product_type_id: str,
    category_id: str,
    description: str | None,
    metadata: dict[str, str],
    suffix_seed: str,
) -> str:
    base_input = {
        "name": name,
        "productType": product_type_id,
        "category": category_id,
        "metadata": metadata_list(metadata),
    }
    desc = description_to_editorjs(description)
    if desc:
        base_input["description"] = desc

    attempt_slug = slug
    for attempt in range(_MAX_SLUG_RETRY):
        try:
            payload = await run_mutation(
                client, _CREATE_PRODUCT, {"input": {**base_input, "slug": attempt_slug}},
                "productCreate",
            )
            return payload["product"]["id"]
        except SaleorError as exc:
            if getattr(exc, "slug_conflict", False) and attempt < _MAX_SLUG_RETRY - 1:
                attempt_slug = with_suffix(slug, f"{suffix_seed}-{attempt + 1}" if attempt else suffix_seed)
                log.warning("product_slug_conflict_retry", slug=attempt_slug)
                continue
            raise
    raise SaleorError(f"product slug exhausted retries: {slug}")  # pragma: no cover


async def update_product(
    client: SaleorClient,
    saleor_id: str,
    *,
    name: str,
    category_id: str,
    description: str | None,
    metadata: dict[str, str],
) -> str:
    inp: dict = {"name": name, "category": category_id, "metadata": metadata_list(metadata)}
    desc = description_to_editorjs(description)
    if desc:
        inp["description"] = desc
    payload = await run_mutation(
        client, _UPDATE_PRODUCT, {"id": saleor_id, "input": inp}, "productUpdate"
    )
    return payload["product"]["id"]


async def create_variant(client: SaleorClient, *, product_id: str, sku: str) -> str:
    payload = await run_mutation(
        client, _CREATE_VARIANT,
        {"input": {"product": product_id, "sku": sku, "trackInventory": False, "attributes": []}},
        "productVariantCreate",
    )
    return payload["productVariant"]["id"]


async def set_product_published(
    client: SaleorClient, *, product_id: str, channel_id: str, published: bool
) -> None:
    await run_mutation(
        client, _PUBLISH,
        {"id": product_id, "input": {"updateChannels": [{
            "channelId": channel_id,
            "isPublished": published,
            "isAvailableForPurchase": published,
            "visibleInListings": published,
        }]}},
        "productChannelListingUpdate",
    )


async def set_variant_price(
    client: SaleorClient, *, variant_id: str, channel_id: str, price: str
) -> None:
    await run_mutation(
        client, _SET_PRICE,
        {"id": variant_id, "input": [{"channelId": channel_id, "price": price}]},
        "productVariantChannelListingUpdate",
    )


async def fetch_product_state(client: SaleorClient, saleor_id: str) -> dict | None:
    """Текущее состояние Saleor-продукта: name, metafields(dict), variants[]."""
    data = await query_data(client, _PRODUCT_STATE, {"id": saleor_id})
    return data.get("product")


# ── Media (product images) ────────────────────────────────────────────────

_CREATE_MEDIA = """
mutation($product: ID!, $image: Upload!, $alt: String){
  productMediaCreate(input:{product:$product, image:$image, alt:$alt}){
    media{ id }
    errors{ field message code }
  }
}
"""

_LIST_MEDIA = """
query($id: ID!){ product(id:$id){ media{ id } } }
"""

_DELETE_MEDIA = """
mutation($id: ID!){ productMediaDelete(id:$id){ errors{ field message } } }
"""


def _image_ext_and_type(content: bytes) -> tuple[str, str]:
    """Sniff format from magic bytes — Saleor validates the uploaded image."""
    if content[:8] == b"\x89PNG\r\n\x1a\n":
        return "png", "image/png"
    if content[:3] == b"\xff\xd8\xff":
        return "jpg", "image/jpeg"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "webp", "image/webp"
    if content[:6] in (b"GIF87a", b"GIF89a"):
        return "gif", "image/gif"
    return "png", "image/png"  # fallback; Saleor re-checks with Pillow


async def list_product_media(client: SaleorClient, product_id: str) -> list[str]:
    data = await query_data(client, _LIST_MEDIA, {"id": product_id})
    return [m["id"] for m in ((data.get("product") or {}).get("media") or [])]


async def delete_all_product_media(client: SaleorClient, product_id: str) -> int:
    ids = await list_product_media(client, product_id)
    for mid in ids:
        await run_mutation(client, _DELETE_MEDIA, {"id": mid}, "productMediaDelete")
    return len(ids)


async def create_product_media(
    client: SaleorClient, *, product_id: str, content: bytes, alt: str = ""
) -> str:
    ext, ctype = _image_ext_and_type(content)
    variables = {"product": product_id, "image": None, "alt": alt}
    body = await client.execute_upload(
        _CREATE_MEDIA, variables,
        file_field_path="variables.image",
        filename=f"image.{ext}", content=content, content_type=ctype,
    )
    if body.get("errors"):
        raise SaleorError(f"productMediaCreate: top-level error: {body['errors']}")
    payload = (body.get("data") or {}).get("productMediaCreate") or {}
    errs = payload.get("errors") or []
    if errs:
        raise SaleorError(f"productMediaCreate: {errs}")
    return payload["media"]["id"]
