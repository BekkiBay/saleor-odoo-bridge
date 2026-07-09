"""saleor.binding repository — external ID mapping через Odoo JSON-2.

Реализует ADR-0007: lookup Odoo record by Saleor ID. Хранит state/error.
"""

from __future__ import annotations

from datetime import datetime

import structlog

from saleor_bridge.odoo.client import OdooClient

log = structlog.get_logger()

_MODEL = "saleor.binding"

# Маркер «реального Saleor-объекта ещё нет» (failed до первого успешного create).
# saleor_id required+unique, поэтому для visibility пишем sentinel, но трактуем его
# как «binding отсутствует» (см. find_saleor_id) → retry уходит в create-путь.
_SENTINEL_PREFIX = "<"

# product.product (варианты) удаляются каскадом при wipe products → чистим binding.
# Атрибуты wipe НЕ трогает (ensure_attribute найдёт их по имени и перепривяжет).
_OUTBOUND_MODELS = ["product.template", "product.product", "product.category", "product.type"]


def _is_sentinel(saleor_id: str | None) -> bool:
    return bool(saleor_id) and str(saleor_id).startswith(_SENTINEL_PREFIX)


class BindingRepository:
    def __init__(self, odoo: OdooClient) -> None:
        self.odoo = odoo

    async def delete_outbound(self) -> int:
        """Удалить все outbound-биндинги (product.template/category/type).

        Нужно после `wipe` Saleor-каталога: иначе bulk-seed уйдёт в update-путь по
        мёртвым saleor_id. Возвращает число удалённых.
        """
        ids = await self.odoo.search(_MODEL, [("model_name", "in", _OUTBOUND_MODELS)])
        if ids:
            await self.odoo.call(_MODEL, "unlink", ids=ids)
        return len(ids)

    async def delete_out(self, model_name: str, odoo_id: int) -> None:
        """Удалить binding по (model_name, odoo_id). No-op если нет (Phase 3.5: archive variant)."""
        ids = await self.odoo.search(
            _MODEL, [("model_name", "=", model_name), ("odoo_id", "=", odoo_id)]
        )
        if ids:
            await self.odoo.call(_MODEL, "unlink", ids=ids)

    async def delete_by_saleor_id(self, model_name: str, saleor_id: str) -> None:
        """Удалить binding по (model_name, saleor_id) — для stale Saleor-варианта в reconcile."""
        ids = await self.odoo.search(
            _MODEL, [("model_name", "=", model_name), ("saleor_id", "=", saleor_id)]
        )
        if ids:
            await self.odoo.call(_MODEL, "unlink", ids=ids)

    async def find_odoo_id(self, model_name: str, saleor_id: str) -> int | None:
        rows = await self.odoo.search_read(
            _MODEL,
            [("model_name", "=", model_name), ("saleor_id", "=", saleor_id)],
            ["odoo_id"],
            limit=1,
        )
        return rows[0]["odoo_id"] if rows else None

    async def find_saleor_id(self, model_name: str, odoo_id: int) -> str | None:
        """Reverse lookup для outbound flow (Odoo → Saleor): по odoo_id → saleor_id.

        Sentinel-значения (failed-заглушки без реального Saleor-объекта) трактуем как
        «нет binding» → retry пойдёт в create-путь, а не в update по мусорному ID.
        """
        rows = await self.odoo.search_read(
            _MODEL,
            [("model_name", "=", model_name), ("odoo_id", "=", odoo_id)],
            ["saleor_id"],
            limit=1,
        )
        if not rows:
            return None
        saleor_id = rows[0]["saleor_id"]
        return None if _is_sentinel(saleor_id) else saleor_id

    async def upsert_out(
        self,
        model_name: str,
        saleor_id: str,
        odoo_id: int,
        *,
        state: str = "synced",
        error: str | None = None,
    ) -> int:
        """Outbound upsert — ключ по odoo_id (стабилен для Odoo→Saleor).

        Перезаписывает в т.ч. sentinel-заглушку (saleor_id <unsynced:..> → реальный id),
        не плодя дубль и не нарушая partial-unique (model_name, odoo_id).
        """
        now = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
        existing = await self.odoo.search(
            _MODEL,
            [("model_name", "=", model_name), ("odoo_id", "=", odoo_id)],
            limit=1,
        )
        vals = {
            "model_name": model_name,
            "saleor_id": saleor_id,
            "odoo_id": odoo_id,
            "sync_state": state,
            "error_message": error or False,
            "last_sync_out": now,
        }
        if existing:
            await self.odoo.write(_MODEL, [existing[0]], vals)
            return existing[0]
        return await self.odoo.create(_MODEL, vals)

    async def upsert(
        self,
        model_name: str,
        saleor_id: str,
        odoo_id: int,
        *,
        direction: str = "in",  # "in" = Saleor→Odoo
        state: str = "synced",
        error: str | None = None,
    ) -> int:
        now = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
        existing = await self.odoo.search(
            _MODEL,
            [("model_name", "=", model_name), ("saleor_id", "=", saleor_id)],
            limit=1,
        )
        vals = {
            "model_name": model_name,
            "saleor_id": saleor_id,
            "odoo_id": odoo_id,
            "sync_state": state,
            "error_message": error or False,
        }
        if direction == "in":
            vals["last_sync_in"] = now
        else:
            vals["last_sync_out"] = now

        if existing:
            await self.odoo.write(_MODEL, [existing[0]], vals)
            return existing[0]
        return await self.odoo.create(_MODEL, vals)

    async def touch_out(self, model_name: str, odoo_id: int) -> None:
        """Обновить только last_sync_out существующего binding, не трогая state/error.

        Phase 3.3: stock-sync переиспользует catalog-binding (product.template) для
        резолва Saleor-продукта; нам нужно отметить «остаток отправлен», но НЕ
        затирать catalog sync_state ('diverged'/'failed'). No-op если binding нет.
        """
        existing = await self.odoo.search(
            _MODEL, [("model_name", "=", model_name), ("odoo_id", "=", odoo_id)], limit=1
        )
        if existing:
            now = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
            await self.odoo.write(_MODEL, [existing[0]], {"last_sync_out": now})

    async def mark_failed_out(self, model_name: str, odoo_id: int, error: str) -> None:
        """Outbound (Odoo→Saleor) failure: помечаем binding по odoo_id (ADR-0008)."""
        existing = await self.odoo.search(
            _MODEL,
            [("model_name", "=", model_name), ("odoo_id", "=", odoo_id)],
            limit=1,
        )
        vals = {"sync_state": "failed", "error_message": error[:2000]}
        if existing:
            await self.odoo.write(_MODEL, [existing[0]], vals)
        else:
            await self.odoo.create(
                _MODEL,
                {"model_name": model_name, "saleor_id": f"<unsynced:{odoo_id}>", "odoo_id": odoo_id, **vals},
            )

    async def mark_failed(self, model_name: str, saleor_id: str, error: str) -> None:
        existing = await self.odoo.search(
            _MODEL,
            [("model_name", "=", model_name), ("saleor_id", "=", saleor_id)],
            limit=1,
        )
        vals = {"sync_state": "failed", "error_message": error[:2000]}
        if existing:
            await self.odoo.write(_MODEL, [existing[0]], vals)
        else:
            # Создаём binding-заглушку чтобы failed был виден в dashboard.
            # odoo_id=0 — placeholder (record не создался).
            await self.odoo.create(
                _MODEL, {"model_name": model_name, "saleor_id": saleor_id, "odoo_id": 0, **vals}
            )
