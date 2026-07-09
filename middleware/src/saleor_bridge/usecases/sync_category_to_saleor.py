"""Usecase: sync product.category Odoo → Saleor (ADR-0013, reverse flow).

Идемпотентно: binding по odoo_id → update | create. Родитель гарантируется
рекурсивно (топология). Защита от циклов: depth > 10 → ошибка.

Phase 3.2 hardening:
- create-секция под Redis-локом (model, odoo_id) — против гонки дублей, когда
  категорию одновременно создаёт свой job И рекурсивный ensure-parent ребёнка.
- parent-move НЕ propagateable в Saleor (CategoryInput без parent, нет move-мутации).
  При расхождении parent логируем WARNING и помечаем binding 'diverged' (видно в
  Bindings dashboard). Имя при этом всё равно обновляем. Re-parent — через wipe+seed.
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
    """parent_id цепочка глубже _MAX_DEPTH — вероятно цикл в Odoo."""


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

    # Родитель раньше ребёнка (вне self-лока: parent берёт свой лок).
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

    # Критическая секция check-or-create под локом (anti-dup race).
    diverged = False
    error_msg: str | None = None
    async with odoo_record_lock(redis_url, f"{_MODEL}:{odoo_id}"):
        existing = await binding_repo.find_saleor_id(_MODEL, odoo_id)
        if existing:
            saleor_id = await cat_mut.update_category(client, existing, name=category.name)
            created = False
            # parent-move detection (Saleor не умеет re-parent, см. docstring)
            current_parent = await cat_mut.fetch_parent_id(client, existing)
            if current_parent != parent_saleor_id:
                diverged = True
                error_msg = (
                    f"parent-move not propagated: Odoo parent={category.parent_external_id} "
                    f"(saleor {parent_saleor_id}) != Saleor parent {current_parent}. "
                    f"Saleor API не поддерживает re-parent; используйте wipe+seed."
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
