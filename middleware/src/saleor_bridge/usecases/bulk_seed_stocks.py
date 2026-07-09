"""Bulk seed остатков: все активные варианты Odoo → Saleor (Phase 3.3, ADR-0013 стиль).

Идемпотентно (productVariantStocksUpdate = upsert). Варианты без catalog-binding
(товар не засеян в Saleor) считаются skip — не ошибка.
"""

from __future__ import annotations

from collections.abc import Callable

import structlog

from saleor_bridge.adapters.odoo.binding import BindingRepository
from saleor_bridge.adapters.saleor.factory import get_saleor_client
from saleor_bridge.config import Settings
from saleor_bridge.odoo.client import OdooClient
from saleor_bridge.usecases.sync_stock_to_saleor import (
    CatalogBindingMissing,
    sync_stock_to_saleor,
)

log = structlog.get_logger()

ProgressCb = Callable[[str, int, int], None]

_VARIANT = "product.product"


async def run_bulk_seed_stocks(
    settings: Settings, *, progress: ProgressCb | None = None
) -> dict:
    odoo = OdooClient(url=settings.odoo_url, db=settings.odoo_db, api_key=settings.odoo_api_key)
    binding_repo = BindingRepository(odoo)
    client = await get_saleor_client(settings)

    pp_ids = await odoo.search(_VARIANT, [("active", "=", True)])
    summary: dict = {
        "total": len(pp_ids), "synced": 0, "skip": 0, "failed": 0, "errors": [],
        "safety_buffer": settings.stock_safety_buffer,
    }

    for i, pp_id in enumerate(pp_ids, 1):
        try:
            res = await sync_stock_to_saleor(
                pp_id, client, odoo, binding_repo, safety_buffer=settings.stock_safety_buffer
            )
            if res.ok:
                summary["synced"] += 1
            else:
                summary["skip"] += 1
        except CatalogBindingMissing:
            summary["skip"] += 1  # товар не в каталоге Saleor — норм
        except Exception as exc:  # noqa: BLE001
            summary["failed"] += 1
            summary["errors"].append(f"variant {pp_id}: {exc}")
            log.warning("bulk_stock_failed", pp_id=pp_id, error=str(exc))
        if progress:
            progress("stocks", i, len(pp_ids))

    return summary
