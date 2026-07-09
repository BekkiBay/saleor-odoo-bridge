"""Usecase: sync product.template Odoo → Saleor (reverse flow).

1 product → 1 product + 1 dummy variant (ADR-0012), без stock (ADR-0014).
Idempotent через saleor.binding. Divergence detection per ADR-0006 (Odoo wins).
channel_id и product_type_id резолвит вызывающий (task / bulk_seed).
"""

from __future__ import annotations

import hashlib

import structlog

from saleor_bridge.adapters.odoo import product as prod_adapter
from saleor_bridge.adapters.odoo.binding import BindingRepository
from saleor_bridge.adapters.saleor import product_mutations as pm
from saleor_bridge.adapters.saleor.slug import slugify
from saleor_bridge.odoo.client import OdooClient
from saleor_bridge.saleor.client import SaleorClient
from saleor_bridge.usecases.result import SyncResult
from saleor_bridge.usecases.sync_category_to_saleor import sync_category_to_saleor

log = structlog.get_logger()

_MODEL = "product.template"
_CAT_MODEL = "product.category"


def _metadata(product) -> dict[str, str]:
    return {
        "odoo_id": product.external_id,
        "odoo_synced_name": product.name,
        "odoo_write_date": product.write_date or "",
    }


async def _log_divergence(odoo: OdooClient, odoo_id: int, saleor_name: str, odoo_name: str) -> None:
    """Записать в chatter product.template (ADR-0006). Best-effort."""
    body = (
        f"⚠️ Saleor divergence: имя в Saleor было изменено вручную на "
        f"'{saleor_name}'. Перезаписано значением из Odoo '{odoo_name}' "
        f"(ADR-0006: Odoo wins)."
    )
    try:
        await odoo.call(_MODEL, "message_post", ids=[odoo_id], body=body)
    except Exception as exc:  # noqa: BLE001
        log.warning("divergence_chatter_failed", odoo_id=odoo_id, error=str(exc))


async def sync_product_to_saleor(
    odoo_id: int,
    client: SaleorClient,
    odoo: OdooClient,
    binding_repo: BindingRepository,
    *,
    channel_id: str,
    product_type_id: str,
    redis_url: str | None = None,
) -> SyncResult:
    product = await prod_adapter.fetch_product(odoo, odoo_id)
    if product is None:
        return SyncResult(ok=False, message=f"product {odoo_id} not found in Odoo")

    existing = await binding_repo.find_saleor_id(_MODEL, odoo_id)

    # ── archive: inactive product → unpublish (ADR подводные камни) ──
    if not product.active:
        if existing:
            await pm.set_product_published(client, product_id=existing, channel_id=channel_id, published=False)
            await binding_repo.upsert_out(_MODEL, existing, odoo_id, state="synced")
            log.info("product_archived", odoo_id=odoo_id, saleor_id=existing)
            return SyncResult(ok=True, odoo_id=odoo_id, message="product unpublished (archived)")
        log.info("product_inactive_skipped", odoo_id=odoo_id)
        return SyncResult(ok=True, odoo_id=odoo_id, message="inactive, never synced — skipped")

    # ── ensure category synced first ──
    cat_saleor_id: str | None = None
    if product.category_external_id:
        cat_odoo_id = int(product.category_external_id)
        cat_saleor_id = await binding_repo.find_saleor_id(_CAT_MODEL, cat_odoo_id)
        if cat_saleor_id is None:
            await sync_category_to_saleor(cat_odoo_id, client, odoo, binding_repo, redis_url=redis_url)
            cat_saleor_id = await binding_repo.find_saleor_id(_CAT_MODEL, cat_odoo_id)
    if cat_saleor_id is None:
        return SyncResult(ok=False, message=f"category for product {odoo_id} unresolved")

    # Main image (image_1920) — synced as product media; sha gates re-upload.
    img_bytes = await prod_adapter.fetch_product_image(odoo, odoo_id)
    img_sha = hashlib.sha256(img_bytes).hexdigest() if img_bytes else ""

    meta = _metadata(product)
    meta["odoo_image_sha"] = img_sha
    price = str(product.list_price)

    if existing:
        state = await pm.fetch_product_state(client, existing)
        old_sha = ""
        if state:
            metafields = state.get("metafields") or {}
            old_sha = metafields.get("odoo_image_sha") or ""
            synced_name = metafields.get("odoo_synced_name")
            current_name = state.get("name")
            if synced_name and current_name and current_name != synced_name:
                await _log_divergence(odoo, odoo_id, current_name, product.name)
        await pm.update_product(
            client, existing, name=product.name, category_id=cat_saleor_id,
            description=product.description, metadata=meta,
        )
        # Publish ДО set_variant_price (иначе PRODUCT_NOT_ASSIGNED_TO_CHANNEL).
        await pm.set_product_published(client, product_id=existing, channel_id=channel_id, published=True)
        # Image: re-sync only when checksum changed (handles add/replace/remove).
        if img_sha != old_sha:
            await pm.delete_all_product_media(client, existing)
            if img_bytes:
                await pm.create_product_media(client, product_id=existing, content=img_bytes)
            log.info("product_image_synced", odoo_id=odoo_id, saleor_id=existing, has_image=bool(img_bytes))
        # Multi-variant: варианты/цены owns sync_template_variants_to_saleor (Phase 3.5).
        if not product.has_variants:
            variants = (state or {}).get("variants") or []
            variant_id = variants[0]["id"] if variants else await pm.create_variant(
                client, product_id=existing, sku=product.sku
            )
            await pm.set_variant_price(client, variant_id=variant_id, channel_id=channel_id, price=price)
        await binding_repo.upsert_out(_MODEL, existing, odoo_id, state="synced")
        log.info("product_updated", odoo_id=odoo_id, saleor_id=existing)
        return SyncResult(ok=True, odoo_id=odoo_id, message="product updated")

    # ── create ──
    slug = f"{slugify(product.name)}-{slugify(product.sku)}"
    product_id = await pm.create_product(
        client, name=product.name, slug=slug, product_type_id=product_type_id,
        category_id=cat_saleor_id, description=product.description, metadata=meta,
        suffix_seed=product.external_id,
    )
    # Publish ДО set_variant_price (иначе PRODUCT_NOT_ASSIGNED_TO_CHANNEL).
    await pm.set_product_published(client, product_id=product_id, channel_id=channel_id, published=True)
    if img_bytes:
        await pm.create_product_media(client, product_id=product_id, content=img_bytes)
        log.info("product_image_synced", odoo_id=odoo_id, saleor_id=product_id, has_image=True)
    # Single-variant: dummy variant тут; multi-variant — reconcile (Phase 3.5).
    if not product.has_variants:
        variant_id = await pm.create_variant(client, product_id=product_id, sku=product.sku)
        await pm.set_variant_price(client, variant_id=variant_id, channel_id=channel_id, price=price)
    await binding_repo.upsert_out(_MODEL, product_id, odoo_id, state="synced")
    log.info("product_created", odoo_id=odoo_id, saleor_id=product_id, sku=product.sku)
    return SyncResult(ok=True, odoo_id=odoo_id, message="product created")
