"""Usecase: reconcile the Odoo product.template variant set → Saleor.

Authoritative reconciliation: desired (active product.product of the template) vs
current (Saleor variants). Creates new ones (bulk, ADR-0024), adopts/updates existing
ones, deletes stale ones (dummy→real migration, ADR-0025). Idempotent.

The pure diff function `diff_variants` is kept separate from I/O for unit tests.
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
    """Reconciliation plan. `keep` — present in both systems (update/adopt),
    `create` — Odoo only, `delete` — stale Saleor variants (sku → id)."""

    keep: list[Variant] = field(default_factory=list)
    create: list[Variant] = field(default_factory=list)
    delete: dict[str, str] = field(default_factory=dict)


def diff_variants(desired: list[Variant], current_skus: dict[str, str]) -> VariantDiff:
    """desired (Odoo) vs current (Saleor {sku: id}) → add/keep/delete plan. Pure function."""
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
        # Template not synced yet (template-sync creates the product first) — not an error.
        return SyncResult(ok=True, odoo_id=template_id, message="no product binding — skipped")

    desired = await variant_adapter.fetch_variants_for_template(odoo, template_id)
    # Guard: 0 active Odoo variants (data anomaly / all archived) → do NOT touch
    # Saleor. Otherwise an empty desired set would delete the working dummy variant (S7 regression).
    # Archiving the whole product is handled by sync_product_to_saleor (unpublish).
    if not desired:
        log.info("template_variants_skip_empty", template_id=template_id)
        return SyncResult(ok=True, odoo_id=template_id, message="no active variants — Saleor untouched")

    state = await pm.fetch_product_state(client, product_saleor_id)
    current = {v["sku"]: v["id"] for v in (state or {}).get("variants") or []}
    diff = diff_variants(desired, current)

    counts = {"create": 0, "keep": 0, "delete": 0}

    # keep: adopt/update one at a time (ensure_variant itself decides adopt vs price-update).
    for v in diff.keep:
        await ensure_variant(client, binding_repo, v, product_saleor_id, current, channel_id=channel_id)
        counts["keep"] += 1

    # create: bulk in one call (ADR-0024: bulk for generating the set).
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

    # delete: stale Saleor variants (dummy after real ones appear, ADR-0025).
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
