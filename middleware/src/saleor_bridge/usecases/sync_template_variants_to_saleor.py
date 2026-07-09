"""Usecase: реконсиляция набора вариантов шаблона Odoo → Saleor (Phase 3.5).

Авторитетная сверка: desired (active product.product шаблона) vs current (Saleor
variants). Создаёт новые (bulk, ADR-0024), усыновляет/обновляет существующие,
удаляет лишние (миграция dummy→real, ADR-0025). Идемпотентно.

Чистая diff-функция `diff_variants` отделена от I/O ради unit-тестов.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from saleor_bridge.adapters.odoo import variant as variant_adapter
from saleor_bridge.adapters.odoo.binding import BindingRepository
from saleor_bridge.adapters.saleor import product_mutations as pm
from saleor_bridge.adapters.saleor import variant_mutations as vm
from saleor_bridge.domain.variants import Variant
from saleor_bridge.odoo.client import OdooClient
from saleor_bridge.saleor.client import SaleorClient
from saleor_bridge.usecases.result import SyncResult
from saleor_bridge.usecases.sync_variant_to_saleor import (
    ensure_variant,
    resolve_attribute_input,
    variant_bulk_input,
)

log = structlog.get_logger()

_TMPL = "product.template"
_VARIANT = "product.product"


@dataclass
class VariantDiff:
    """План реконсиляции. `keep` — есть в обеих системах (update/adopt),
    `create` — только в Odoo, `delete` — лишние Saleor-варианты (sku → id)."""

    keep: list[Variant] = field(default_factory=list)
    create: list[Variant] = field(default_factory=list)
    delete: dict[str, str] = field(default_factory=dict)


def diff_variants(desired: list[Variant], current_skus: dict[str, str]) -> VariantDiff:
    """desired (Odoo) vs current (Saleor {sku: id}) → план add/keep/delete. Чистая функция."""
    desired_skus = {v.sku for v in desired}
    diff = VariantDiff()
    for v in desired:
        (diff.keep if v.sku in current_skus else diff.create).append(v)
    diff.delete = {sku: vid for sku, vid in current_skus.items() if sku not in desired_skus}
    return diff


async def sync_template_variants_to_saleor(
    template_id: int,
    client: SaleorClient,
    odoo: OdooClient,
    binding_repo: BindingRepository,
    *,
    channel_id: str,
) -> SyncResult:
    product_saleor_id = await binding_repo.find_saleor_id(_TMPL, template_id)
    if product_saleor_id is None:
        # Шаблон ещё не синкнут (template-sync создаёт продукт первым) — не ошибка.
        return SyncResult(ok=True, odoo_id=template_id, message="no product binding — skipped")

    desired = await variant_adapter.fetch_variants_for_template(odoo, template_id)
    # Guard: 0 активных Odoo-вариантов (data anomaly / все архивированы) → НЕ трогаем
    # Saleor. Иначе пустой desired удалил бы рабочий dummy-вариант (S7 regression).
    # Архивацию продукта целиком обрабатывает sync_product_to_saleor (unpublish).
    if not desired:
        log.info("template_variants_skip_empty", template_id=template_id)
        return SyncResult(ok=True, odoo_id=template_id, message="no active variants — Saleor untouched")

    state = await pm.fetch_product_state(client, product_saleor_id)
    current = {v["sku"]: v["id"] for v in (state or {}).get("variants") or []}
    diff = diff_variants(desired, current)

    counts = {"create": 0, "keep": 0, "delete": 0}

    # keep: adopt/update по одному (ensure_variant сам решит adopt vs price-update).
    for v in diff.keep:
        await ensure_variant(client, binding_repo, v, product_saleor_id, current, channel_id=channel_id)
        counts["keep"] += 1

    # create: bulk одним вызовом (ADR-0024: bulk для генерации набора).
    if diff.create:
        bulk_input = []
        for v in diff.create:
            attr_input = await resolve_attribute_input(binding_repo, v)
            bulk_input.append(variant_bulk_input(v, channel_id, attr_input))
        created = await vm.bulk_create_variants(client, product_id=product_saleor_id, variants=bulk_input)
        for v in diff.create:
            saleor_id = created[v.sku]
            await binding_repo.upsert_out(_VARIANT, saleor_id, int(v.external_id), state="synced")
            counts["create"] += 1

    # delete: лишние Saleor-варианты (dummy после появления реальных, ADR-0025).
    for vid in diff.delete.values():
        await vm.delete_variant(client, vid)
        await binding_repo.delete_by_saleor_id(_VARIANT, vid)
        counts["delete"] += 1

    await binding_repo.touch_out(_TMPL, template_id)
    log.info("template_variants_synced", template_id=template_id, **counts)
    return SyncResult(
        ok=True, odoo_id=template_id,
        message=f"variants reconciled create={counts['create']} keep={counts['keep']} delete={counts['delete']}",
    )
