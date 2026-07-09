"""Odoo 19 JSON-2 REST client.

Reference: https://www.odoo.com/documentation/19.0/developer/reference/external_api.html

Endpoint: POST /json/2/<model>/<method> with named kwargs in the body.
Auth: Authorization: bearer <api-key>, X-Odoo-Database: <db>.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

log = structlog.get_logger()


class OdooError(RuntimeError):
    """Odoo returned 4xx/5xx (constraint, validation, etc.)."""


class OdooClient:
    def __init__(self, url: str, db: str, api_key: str, timeout: float = 30.0) -> None:
        self.url = url.rstrip("/")
        self.db = db
        self.api_key = api_key
        self.timeout = timeout
        self._headers = {
            "Authorization": f"bearer {api_key}",
            "X-Odoo-Database": db,
            "Content-Type": "application/json",
            "User-Agent": "saleor-bridge/0.1.0",
        }

    async def call(self, model: str, method: str, **kwargs: Any) -> Any:
        endpoint = f"{self.url}/json/2/{model}/{method}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(endpoint, headers=self._headers, json=kwargs)
            if r.status_code >= 400:
                log.warning(
                    "odoo_call_failed",
                    model=model, method=method, status=r.status_code, body=r.text[:500],
                )
                raise OdooError(f"{model}.{method} HTTP {r.status_code}: {r.text[:300]}")
            return r.json()

    # ── convenience ORM wrappers ──────────────────────────────────────────

    async def search(self, model: str, domain: list, limit: int | None = None) -> list[int]:
        kw: dict[str, Any] = {"domain": domain}
        if limit is not None:
            kw["limit"] = limit
        return await self.call(model, "search", **kw)

    async def search_read(
        self, model: str, domain: list, fields: list[str], limit: int | None = None
    ) -> list[dict]:
        kw: dict[str, Any] = {"domain": domain, "fields": fields}
        if limit is not None:
            kw["limit"] = limit
        return await self.call(model, "search_read", **kw)

    async def read(self, model: str, ids: list[int], fields: list[str]) -> list[dict]:
        return await self.call(model, "read", ids=ids, fields=fields)

    async def create(self, model: str, vals: dict) -> int:
        """create takes vals_list in JSON-2. Returns the first id."""
        res = await self.call(model, "create", vals_list=[vals])
        return res[0] if isinstance(res, list) else res

    async def write(self, model: str, ids: list[int], vals: dict) -> bool:
        return await self.call(model, "write", ids=ids, vals=vals)

    async def version(self) -> dict:
        """GET /web/version — public, no auth required. Health-check."""
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{self.url}/web/version")
            r.raise_for_status()
            return r.json()
