"""Bulk seed orchestration: the entire Odoo catalog → Saleor (ADR-0013).

Idempotent. Order: ProductType → categories (topologically) → products.
Rich progress lives in the CLI; an optional progress callback is passed in here.
"""

from __future__ import annotations

from collections.abc import Callable

import structlog

from saleor_bridge.adapters.odoo import category as cat_adapter
from saleor_bridge.adapters.odoo import product as prod_adapter
from saleor_bridge.adapters.odoo.binding import BindingRepository
from saleor_bridge.adapters.saleor.catalog_admin import resolve_channel
from saleor_bridge.adapters.saleor.factory import get_saleor_client
from saleor_bridge.adapters.saleor.product_type_mutations import ensure_product_type
from saleor_bridge.config import Settings
from saleor_bridge.domain.category import ProductCategory
from saleor_bridge.odoo.client import OdooClient
from saleor_bridge.usecases.sync_category_to_saleor import sync_category_to_saleor
from saleor_bridge.usecases.sync_product_to_saleor import sync_product_to_saleor

log = structlog.get_logger()

_CAT_MODEL = "product.category"
_PROD_MODEL = "product.template"
_MAX_DEPTH = 10

ProgressCb = Callable[[str, int, int], None]


class CategoryCycle(RuntimeError):
    """Cycle in the category tree (parent_id) — deeper than _MAX_DEPTH."""


def topological_sort(categories: list[ProductCategory]) -> list[ProductCategory]:
    """Parents before children. Only within the given set.

    Raises CategoryCycle on a cycle or depth > _MAX_DEPTH.
    """
    by_id = {c.external_id: c for c in categories}
    state: dict[str, int] = {}  # 0 = visiting, 1 = done
    out: list[ProductCategory] = []

    def visit(cat: ProductCategory, depth: int) -> None:
        if depth > _MAX_DEPTH:
            raise CategoryCycle(f"depth > {_MAX_DEPTH} at {cat.external_id}")
        st = state.get(cat.external_id)
        if st == 1:
            return
        if st == 0:
            raise CategoryCycle(f"cycle detected at {cat.external_id}")
        state[cat.external_id] = 0
        pid = cat.parent_external_id
        if pid and pid in by_id:
            visit(by_id[pid], depth + 1)
        state[cat.external_id] = 1
        out.append(cat)

    for c in categories:
        visit(c, 0)
    return out


async def _collect_catalog_categories(
    odoo: OdooClient, product_category_ids: set[int]
) -> list[ProductCategory]:
    """All categories reachable upward via parent_id from the product categories."""
    all_ids = await odoo.search(_CAT_MODEL, [])
    all_cats = await cat_adapter.list_categories(odoo, all_ids)
    by_id = {c.external_id: c for c in all_cats}

    reachable: dict[str, ProductCategory] = {}
    for cid in product_category_ids:
        cur: str | None = str(cid)
        depth = 0
        while cur and cur in by_id and cur not in reachable:
            if depth > _MAX_DEPTH:
                raise CategoryCycle(f"parent chain too deep from {cid}")
            cat = by_id[cur]
            reachable[cur] = cat
            cur = cat.parent_external_id
            depth += 1
    return list(reachable.values())


async def run_bulk_seed(
    settings: Settings,
    *,
    dry_run: bool = False,
    progress: ProgressCb | None = None,
) -> dict:
    """Main entry point. Returns a summary with statistics."""
    def _progress(stage: str, cur: int, total: int) -> None:
        if progress:
            progress(stage, cur, total)

    odoo = OdooClient(url=settings.odoo_url, db=settings.odoo_db, api_key=settings.odoo_api_key)
    binding_repo = BindingRepository(odoo)

    # ── gather data from Odoo ──
    product_ids = await prod_adapter.list_active_product_ids(odoo)
    products = await prod_adapter.list_products(odoo, product_ids)
    product_cat_ids = {int(p.category_external_id) for p in products if p.category_external_id}
    categories = topological_sort(await _collect_catalog_categories(odoo, product_cat_ids))

    summary: dict = {
        "dry_run": dry_run,
        "categories": {"total": len(categories), "create": 0, "update": 0, "failed": 0},
        "products": {"total": len(products), "create": 0, "update": 0, "skip": 0, "failed": 0},
        "product_type": None,
        "channel": None,
        "errors": [],
    }

    # ── dry-run: plan only (read-only binding lookups) ──
    if dry_run:
        for c in categories:
            existing = await binding_repo.find_saleor_id(_CAT_MODEL, int(c.external_id))
            summary["categories"]["update" if existing else "create"] += 1
        for p in products:
            if not p.active:
                summary["products"]["skip"] += 1
                continue
            existing = await binding_repo.find_saleor_id(_PROD_MODEL, int(p.external_id))
            summary["products"]["update" if existing else "create"] += 1
        summary["product_type"] = settings.saleor_product_type_name
        summary["channel"] = settings.saleor_default_channel
        return summary

    # ── real run ──
    client = await get_saleor_client(settings)
    channel = await resolve_channel(client, settings.saleor_default_channel)
    summary["channel"] = channel
    # Odoo list prices are pushed verbatim; they are assumed to be denominated in
    # the target channel's currency. No conversion is performed.
    summary["currency"] = channel["currencyCode"]
    product_type_id = await ensure_product_type(client, binding_repo, settings.saleor_product_type_name)
    summary["product_type"] = product_type_id

    for i, c in enumerate(categories, 1):
        existing = await binding_repo.find_saleor_id(_CAT_MODEL, int(c.external_id))
        try:
            await sync_category_to_saleor(int(c.external_id), client, odoo, binding_repo, redis_url=settings.redis_url)
            summary["categories"]["update" if existing else "create"] += 1
        except Exception as exc:  # noqa: BLE001
            summary["categories"]["failed"] += 1
            summary["errors"].append(f"category {c.external_id} ({c.name}): {exc}")
            log.warning("bulk_category_failed", odoo_id=c.external_id, error=str(exc))
        _progress("categories", i, len(categories))

    for i, p in enumerate(products, 1):
        existing = await binding_repo.find_saleor_id(_PROD_MODEL, int(p.external_id))
        try:
            res = await sync_product_to_saleor(
                int(p.external_id), client, odoo, binding_repo,
                channel_id=channel["id"], product_type_id=product_type_id, redis_url=settings.redis_url,
            )
            if not p.active:
                summary["products"]["skip"] += 1
            elif res.ok:
                summary["products"]["update" if existing else "create"] += 1
            else:
                summary["products"]["failed"] += 1
                summary["errors"].append(f"product {p.external_id} ({p.sku}): {res.message}")
        except Exception as exc:  # noqa: BLE001
            summary["products"]["failed"] += 1
            summary["errors"].append(f"product {p.external_id} ({p.sku}): {exc}")
            log.warning("bulk_product_failed", odoo_id=p.external_id, error=str(exc))
        _progress("products", i, len(products))

    return summary


async def run_retry_failed(settings: Settings) -> dict:
    """Re-sync all saleor.binding rows with state='failed' (outbound product/category).

    Inbound bindings (res.partner / sale.order) are skipped — their own flow retries them.
    """
    odoo = OdooClient(url=settings.odoo_url, db=settings.odoo_db, api_key=settings.odoo_api_key)
    binding_repo = BindingRepository(odoo)
    rows = await odoo.search_read(
        "saleor.binding", [("sync_state", "=", "failed")], ["model_name", "odoo_id"]
    )
    summary: dict = {"found": len(rows), "ok": 0, "failed": 0, "skipped": 0, "errors": []}
    if not rows:
        return summary

    client = await get_saleor_client(settings)
    channel = await resolve_channel(client, settings.saleor_default_channel)
    product_type_id = await ensure_product_type(client, binding_repo, settings.saleor_product_type_name)

    for r in rows:
        model = r["model_name"]
        odoo_id = int(r["odoo_id"])
        try:
            if model == _CAT_MODEL:
                res = await sync_category_to_saleor(odoo_id, client, odoo, binding_repo, redis_url=settings.redis_url)
            elif model == _PROD_MODEL:
                res = await sync_product_to_saleor(
                    odoo_id, client, odoo, binding_repo,
                    channel_id=channel["id"], product_type_id=product_type_id, redis_url=settings.redis_url,
                )
            else:
                summary["skipped"] += 1
                continue
            if res.ok:
                summary["ok"] += 1
            else:
                summary["failed"] += 1
                summary["errors"].append(f"{model}#{odoo_id}: {res.message}")
        except Exception as exc:  # noqa: BLE001
            summary["failed"] += 1
            summary["errors"].append(f"{model}#{odoo_id}: {exc}")
            log.warning("retry_failed_err", model=model, odoo_id=odoo_id, error=str(exc))
    return summary
