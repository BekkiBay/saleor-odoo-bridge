"""Usecase: sync product.category Odoo → Saleor (ADR-0013, reverse flow).

Idempotent: binding by odoo_id → update | create. The parent is guaranteed
recursively (topology). Cycle protection: depth > 10 → error.

Hardening notes:
- The create section runs under a Redis lock (model, odoo_id) — protects against a
  duplicate-creation race when a category is created by both its own job AND the
  recursive ensure-parent call of a child.
- parent-move is NOT propagatable to Saleor (CategoryInput has no parent, and there
  is no move mutation). On parent divergence we log a WARNING and mark the binding
  'diverged' (visible in the Bindings dashboard). The name is still updated either way.
  Re-parenting requires wipe+seed.
"""

from __future__ import annotations

import structlog

from saleor_bridge.adapters.odoo import category as cat_adapter
from saleor_bridge.adapters.odoo.binding import BindingRepository
from saleor_bridge.adapters.saleor import category_mutations as cat_mut
from saleor_bridge.adapters.saleor.slug import slugify
from saleor_bridge.locks import odoo_record_lock
from saleor_bridge.odoo.client import OdooClient
from saleor_bridge.saleor.client import SaleorClient
from saleor_bridge.usecases.result import SyncResult

log = structlog.get_logger()

_MODEL = "product.category"
_MAX_DEPTH = 10


class CategoryCycle(RuntimeError):
    """parent_id chain deeper than _MAX_DEPTH — likely a cycle in Odoo."""


async def sync_category_to_saleor(
    odoo_id: int,
    client: SaleorClient,
    odoo: OdooClient,
    binding_repo: BindingRepository,
    *,
    redis_url: str | None = None,
    _depth: int = 0,
) -> SyncResult:
    if _depth > _MAX_DEPTH:
        raise CategoryCycle(f"category depth > {_MAX_DEPTH} (cycle?) at odoo_id={odoo_id}")

    category = await cat_adapter.fetch_category(odoo, odoo_id)
    if category is None:
        return SyncResult(ok=False, message=f"category {odoo_id} not found in Odoo")

    # Parent before child (outside the self-lock: the parent takes its own lock).
    parent_saleor_id: str | None = None
    if category.parent_external_id:
        parent_odoo_id = int(category.parent_external_id)
        parent_saleor_id = await binding_repo.find_saleor_id(_MODEL, parent_odoo_id)
        if parent_saleor_id is None:
            await sync_category_to_saleor(
                parent_odoo_id, client, odoo, binding_repo,
                redis_url=redis_url, _depth=_depth + 1,
            )
            parent_saleor_id = await binding_repo.find_saleor_id(_MODEL, parent_odoo_id)

    # Critical check-or-create section under lock (anti-dup race).
    diverged = False
    error_msg: str | None = None
    async with odoo_record_lock(redis_url, f"{_MODEL}:{odoo_id}"):
        existing = await binding_repo.find_saleor_id(_MODEL, odoo_id)
        if existing:
            saleor_id = await cat_mut.update_category(client, existing, name=category.name)
            created = False
            # parent-move detection (Saleor cannot re-parent, see docstring)
            current_parent = await cat_mut.fetch_parent_id(client, existing)
            if current_parent != parent_saleor_id:
                diverged = True
                error_msg = (
                    f"parent-move not propagated: Odoo parent={category.parent_external_id} "
                    f"(saleor {parent_saleor_id}) != Saleor parent {current_parent}. "
                    f"The Saleor API does not support re-parenting; use wipe+seed."
                )
                log.warning("category_parent_diverged", odoo_id=odoo_id, saleor_id=existing,
                            desired_parent=parent_saleor_id, saleor_parent=current_parent)
        else:
            saleor_id = await cat_mut.create_category(
                client,
                name=category.name,
                slug=slugify(category.complete_name),
                parent_saleor_id=parent_saleor_id,
                suffix_seed=category.external_id,
            )
            created = True

        await binding_repo.upsert_out(
            _MODEL, saleor_id, odoo_id,
            state="diverged" if diverged else "synced", error=error_msg,
        )

    log.info("category_synced", odoo_id=odoo_id, saleor_id=saleor_id, created=created, diverged=diverged)
    return SyncResult(ok=True, odoo_id=odoo_id, message=f"category {'created' if created else 'updated'}")
