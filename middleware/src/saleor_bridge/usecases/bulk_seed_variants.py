"""Bulk seed вариантов: миграция существующих product.template → variant bindings.

Phase 3.5 (ADR-0025). Для каждого синканного шаблона прогоняет реконсиляцию набора
вариантов. Для single-variant продуктов (Phase 3.2 dummy) это усыновляет dummy и
создаёт binding product.product → variant. Идемпотентно (повторный прогон — no-op).
"""

from __future__ import annotations

from collections.abc import Callable

import structlog

from saleor_bridge.adapters.odoo.binding import BindingRepository
from saleor_bridge.adapters.saleor.catalog_admin import resolve_channel
from saleor_bridge.adapters.saleor.factory import get_saleor_client
from saleor_bridge.config import Settings
from saleor_bridge.odoo.client import OdooClient
from saleor_bridge.usecases.sync_template_variants_to_saleor import (
    sync_template_variants_to_saleor,
)

log = structlog.get_logger()

ProgressCb = Callable[[str, int, int], None]

_TMPL = "product.template"
_VARIANT = "product.product"


async def run_bulk_seed_variants(settings: Settings, *, progress: ProgressCb | None = None) -> dict:
    odoo = OdooClient(url=settings.odoo_url, db=settings.odoo_db, api_key=settings.odoo_api_key)
    binding_repo = BindingRepository(odoo)
    client = await get_saleor_client(settings)
    channel = await resolve_channel(client, settings.saleor_default_channel)

    rows = await odoo.search_read("saleor.binding", [("model_name", "=", _TMPL)], ["odoo_id"])
    template_ids = sorted({int(r["odoo_id"]) for r in rows})

    summary: dict = {
        "templates": len(template_ids),
        "reconciled": 0,
        "failed": 0,
        "variant_bindings": 0,
        "errors": [],
    }

    for i, tid in enumerate(template_ids, 1):
        try:
            res = await sync_template_variants_to_saleor(
                tid, client, odoo, binding_repo, channel_id=channel["id"]
            )
            if res.ok:
                summary["reconciled"] += 1
            else:
                summary["failed"] += 1
                summary["errors"].append(f"template {tid}: {res.message}")
        except Exception as exc:  # noqa: BLE001
            summary["failed"] += 1
            summary["errors"].append(f"template {tid}: {exc}")
            log.warning("bulk_variants_failed", template_id=tid, error=str(exc))
        if progress:
            progress("variants", i, len(template_ids))

    summary["variant_bindings"] = await odoo.call(
        "saleor.binding", "search_count", domain=[("model_name", "=", _VARIANT)]
    )
    return summary
