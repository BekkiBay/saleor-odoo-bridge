"""Usecase: sync одного product.product Odoo → Saleor ProductVariant (Phase 3.5).

Flow (ADR-0024/0026):
1. product.product → template binding (Saleor product). Нет → CatalogBindingMissing (retry).
2. Резолв attribute-assignments (PTAV → Saleor AttributeValue ids через binding).
   Нет binding атрибута → AttributeBindingMissing (retry; attribute-sync идёт первым).
3. existing variant binding → update (price/barcode); SKU совпал с Saleor-вариантом →
   ADOPT (миграция dummy-варианта Phase 3.2); иначе CREATE (bulk с inline ценой).
4. active=False → delete variant + binding (S4).

Реюзабельные helpers (resolve_attribute_input / ensure_variant) шарятся с
sync_template_variants_to_saleor.
"""

from __future__ import annotations

import structlog

from saleor_bridge.adapters.odoo import variant as variant_adapter
from saleor_bridge.adapters.odoo.binding import BindingRepository
from saleor_bridge.adapters.saleor import product_mutations as pm
from saleor_bridge.adapters.saleor import variant_mutations as vm
from saleor_bridge.domain.variants import Variant
from saleor_bridge.odoo.client import OdooClient
from saleor_bridge.saleor.client import SaleorClient
from saleor_bridge.usecases.result import SyncResult
from saleor_bridge.usecases.sync_stock_to_saleor import CatalogBindingMissing

log = structlog.get_logger()

_TMPL = "product.template"
_VARIANT = "product.product"
_ATTR = "product.attribute"
_VALUE = "product.attribute.value"


class AttributeBindingMissing(RuntimeError):
    """Attribute/value ещё не синкнут в Saleor — retry (attribute-sync идёт первым)."""


async def resolve_attribute_input(binding_repo: BindingRepository, variant: Variant) -> list[dict]:
    """PTAV-assignments варианта → Saleor variant.attributes input. Raise если binding нет."""
    out: list[dict] = []
    for a in variant.attributes:
        attr_id = await binding_repo.find_saleor_id(_ATTR, int(a.attribute_external_id))
        value_id = await binding_repo.find_saleor_id(_VALUE, int(a.value_external_id))
        if attr_id is None or value_id is None:
            raise AttributeBindingMissing(
                f"attribute {a.attribute_external_id}/value {a.value_external_id} not synced"
            )
        out.append(vm.attribute_input(attr_id, value_id))
    return out


def variant_bulk_input(variant: Variant, channel_id: str, attribute_input: list[dict]) -> dict:
    """ProductVariantBulkCreateInput с inline channel listing (цена + доступность)."""
    return {
        "sku": variant.sku,
        "trackInventory": True,
        "attributes": attribute_input,
        "channelListings": [{"channelId": channel_id, "price": str(variant.price)}],
    }


async def ensure_variant(
    client: SaleorClient,
    binding_repo: BindingRepository,
    variant: Variant,
    product_saleor_id: str,
    current: dict[str, str],
    *,
    channel_id: str,
) -> str:
    """Создать/усыновить/обновить ОДИН вариант. Возвращает Saleor variant id.

    `current` — {sku: variant_id} текущих Saleor-вариантов продукта (для adopt).
    """
    odoo_id = int(variant.external_id)
    existing = await binding_repo.find_saleor_id(_VARIANT, odoo_id)

    if existing:
        await pm.set_variant_price(client, variant_id=existing, channel_id=channel_id, price=str(variant.price))
        await binding_repo.upsert_out(_VARIANT, existing, odoo_id, state="synced")
        return existing

    if variant.sku in current:  # adopt существующий Saleor-вариант (миграция dummy, ADR-0025)
        adopted = current[variant.sku]
        await binding_repo.upsert_out(_VARIANT, adopted, odoo_id, state="synced")
        await pm.set_variant_price(client, variant_id=adopted, channel_id=channel_id, price=str(variant.price))
        log.info("variant_adopted", odoo_id=odoo_id, saleor_id=adopted, sku=variant.sku)
        return adopted

    attr_input = await resolve_attribute_input(binding_repo, variant)
    created = await vm.bulk_create_variants(
        client, product_id=product_saleor_id,
        variants=[variant_bulk_input(variant, channel_id, attr_input)],
    )
    saleor_id = created[variant.sku]
    await binding_repo.upsert_out(_VARIANT, saleor_id, odoo_id, state="synced")
    log.info("variant_created", odoo_id=odoo_id, saleor_id=saleor_id, sku=variant.sku)
    return saleor_id


async def sync_variant_to_saleor(
    pp_id: int,
    client: SaleorClient,
    odoo: OdooClient,
    binding_repo: BindingRepository,
    *,
    channel_id: str,
) -> SyncResult:
    variant = await variant_adapter.fetch_variant(odoo, pp_id)
    if variant is None or not variant.template_external_id:
        return SyncResult(ok=False, message=f"variant {pp_id} not found in Odoo")

    # ── archive: variant active=False → delete в Saleor (S4) ──
    # odoo_id=None сигналит вызывающему «живого варианта нет» → пропустить stock-sync.
    if not variant.active:
        existing = await binding_repo.find_saleor_id(_VARIANT, pp_id)
        if existing:
            await vm.delete_variant(client, existing)
            await binding_repo.delete_out(_VARIANT, pp_id)
            log.info("variant_archived", pp_id=pp_id, saleor_id=existing)
            return SyncResult(ok=True, odoo_id=None, message="variant deleted (archived)")
        return SyncResult(ok=True, odoo_id=None, message="inactive, never synced — skipped")

    template_id = int(variant.template_external_id)
    product_saleor_id = await binding_repo.find_saleor_id(_TMPL, template_id)
    if product_saleor_id is None:
        raise CatalogBindingMissing(f"no product.template binding for tmpl {template_id} (variant {pp_id})")

    state = await pm.fetch_product_state(client, product_saleor_id)
    current = {v["sku"]: v["id"] for v in (state or {}).get("variants") or []}

    saleor_id = await ensure_variant(
        client, binding_repo, variant, product_saleor_id, current, channel_id=channel_id
    )
    return SyncResult(ok=True, odoo_id=pp_id, message=f"variant synced {saleor_id}")
