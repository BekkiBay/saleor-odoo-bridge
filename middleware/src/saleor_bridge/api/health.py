"""Health + readiness endpoints. Не падают при degraded deps."""

from __future__ import annotations

import httpx
import redis.asyncio as redis
from fastapi import APIRouter, Depends

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
    """GET /web/version возвращает {version_info: [...], version: ...} в Odoo 19."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{settings.odoo_url.rstrip('/')}/web/version")
            return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


@router.get("/health")
async def health(settings: Settings = Depends(get_settings)) -> dict:
    """Always HTTP 200; компоненты репортятся отдельно."""
    return {
        "status": "ok",
        "redis": "ok" if await _redis_ok(settings) else "fail",
        "odoo": "ok" if await _odoo_ok(settings) else "fail",
    }


@router.get("/ready")
async def ready(settings: Settings = Depends(get_settings)) -> dict:
    """Readiness probe — для kubernetes-стиля. Strict: 503 если что-то fail."""
    redis_state = await _redis_ok(settings)
    odoo_state = await _odoo_ok(settings)
    body = {"redis": redis_state, "odoo": odoo_state}
    if redis_state and odoo_state:
        return {"status": "ready", **body}
    # Fast-fail readiness — но в Phase 3.0 не хотим разваливать compose,
    # поэтому всё равно 200. В Phase 4 заменим на raise HTTPException(503).
    return {"status": "degraded", **body}
