"""saleor.binding repository — external ID mapping via Odoo JSON-2.

Implements ADR-0007: lookup Odoo record by Saleor ID. Stores state/error.
"""

from __future__ import annotations

from datetime import datetime

import structlog

from saleor_bridge.odoo.client import OdooClient

log = structlog.get_logger()

_MODEL = "saleor.binding"

# Marker for "no real Saleor object yet" (failed before the first successful create).
# saleor_id is required+unique, so for visibility we write a sentinel, but we treat it
# as "binding absent" (see find_saleor_id) → retry goes down the create path.
_SENTINEL_PREFIX = "<"

# product.product (variants) are cascade-deleted on wipe products → we clean up the binding.
# wipe does NOT touch attributes (ensure_attribute will find them by name and re-link them).
_OUTBOUND_MODELS = ["product.template", "product.product", "product.category", "product.type"]


def _is_sentinel(saleor_id: str | None) -> bool:
    return bool(saleor_id) and str(saleor_id).startswith(_SENTINEL_PREFIX)


class BindingRepository:
    def __init__(self, odoo: OdooClient) -> None:
        self.odoo = odoo

    async def delete_outbound(self) -> int:
        """Delete all outbound bindings (product.template/category/type).

        Needed after a Saleor catalog `wipe`: otherwise bulk-seed would go down the
        update path against dead saleor_id values. Returns the number deleted.
        """
        ids = await self.odoo.search(_MODEL, [("model_name", "in", _OUTBOUND_MODELS)])
        if ids:
            await self.odoo.call(_MODEL, "unlink", ids=ids)
        return len(ids)

    async def delete_out(self, model_name: str, odoo_id: int) -> None:
        """Delete binding by (model_name, odoo_id). No-op if none exists (used when archiving a variant)."""
        ids = await self.odoo.search(
            _MODEL, [("model_name", "=", model_name), ("odoo_id", "=", odoo_id)]
        )
        if ids:
            await self.odoo.call(_MODEL, "unlink", ids=ids)

    async def delete_by_saleor_id(self, model_name: str, saleor_id: str) -> None:
        """Delete binding by (model_name, saleor_id) — for a stale Saleor variant during reconcile."""
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
        """Reverse lookup for the outbound flow (Odoo → Saleor): odoo_id → saleor_id.

        Sentinel values (failed placeholders without a real Saleor object) are treated as
        "no binding" → retry goes down the create path instead of updating a bogus ID.
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
        """Outbound upsert — keyed by odoo_id (stable for Odoo→Saleor).

        Also overwrites a sentinel placeholder (saleor_id <unsynced:..> → real id),
        without creating a duplicate or violating the partial-unique (model_name, odoo_id).
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
        """Update only last_sync_out on an existing binding, without touching state/error.

        stock-sync reuses the catalog binding (product.template) to resolve the
        Saleor product; we need to mark "stock sent" but must NOT clobber the
        catalog sync_state ('diverged'/'failed'). No-op if the binding doesn't exist.
        """
        existing = await self.odoo.search(
            _MODEL, [("model_name", "=", model_name), ("odoo_id", "=", odoo_id)], limit=1
        )
        if existing:
            now = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
            await self.odoo.write(_MODEL, [existing[0]], {"last_sync_out": now})

    async def mark_failed_out(self, model_name: str, odoo_id: int, error: str) -> None:
        """Outbound (Odoo→Saleor) failure: marks the binding by odoo_id (ADR-0008)."""
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
            # Create a binding placeholder so the failure is visible in the dashboard.
            # odoo_id=0 — placeholder (record wasn't created).
            await self.odoo.create(
                _MODEL, {"model_name": model_name, "saleor_id": saleor_id, "odoo_id": 0, **vals}
            )
