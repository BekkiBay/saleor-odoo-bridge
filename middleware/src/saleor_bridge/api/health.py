"""Health + readiness endpoints."""

from __future__ import annotations

import httpx
import redis.asyncio as redis
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from saleor_bridge.config import Settings, get_settings

router = APIRouter(tags=["health"])


async def _redis_ok(settings: Settings) -> bool:
    try:
        client = redis.from_url(settings.redis_url, socket_connect_timeout=2)
        await client.ping()
        await client.aclose()
        return True
    except Exception:  # noqa: BLE001
        return False


async def _odoo_ok(settings: Settings) -> bool:
    """GET /web/version returns {version_info: [...], version: ...} on Odoo 19."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{settings.odoo_url.rstrip('/')}/web/version")
            return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


@router.get("/health")
async def health(settings: Settings = Depends(get_settings)) -> dict:
    """Liveness: always HTTP 200; each dependency is reported separately."""
    return {
        "status": "ok",
        "redis": "ok" if await _redis_ok(settings) else "fail",
        "odoo": "ok" if await _odoo_ok(settings) else "fail",
    }


@router.get("/ready")
async def ready(settings: Settings = Depends(get_settings)) -> JSONResponse:
    """Readiness probe: HTTP 503 unless every dependency answers.

    Orchestrators route traffic on this, so a degraded bridge must not report
    itself ready — it cannot enqueue or deliver a single event without Redis.
    """
    redis_state = await _redis_ok(settings)
    odoo_state = await _odoo_ok(settings)
    body = {"redis": redis_state, "odoo": odoo_state}
    if redis_state and odoo_state:
        return JSONResponse({"status": "ready", **body})
    return JSONResponse({"status": "degraded", **body}, status_code=503)
