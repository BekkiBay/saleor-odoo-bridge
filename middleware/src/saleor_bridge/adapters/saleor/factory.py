"""Создать аутентифицированный SaleorClient из APL (токен установленного App).

Токен кладёт endpoint `/api/register` при установке Saleor App (см. smoke flow и
scripts/install_bridge_app.py). Fallback — env BRIDGE_SALEOR_APP_TOKEN.
"""

from __future__ import annotations

import structlog

from saleor_bridge.apl.redis_apl import RedisAPL
from saleor_bridge.config import Settings
from saleor_bridge.saleor.client import SaleorClient

log = structlog.get_logger()


class NoSaleorToken(RuntimeError):
    """Нет токена App — нужно установить bridge-app (install_bridge_app.py)."""


async def get_saleor_client(settings: Settings) -> SaleorClient:
    token = settings.saleor_app_token
    if not token:
        apl = RedisAPL(settings.redis_url)
        try:
            auth = await apl.get(settings.saleor_api_url)
        finally:
            await apl.aclose()
        token = auth.token if auth else ""
    if not token:
        raise NoSaleorToken(
            f"нет Saleor App токена для {settings.saleor_api_url} — установи bridge-app "
            f"(python scripts/install_bridge_app.py) либо задай BRIDGE_SALEOR_APP_TOKEN"
        )
    return SaleorClient(api_url=settings.saleor_api_url, app_token=token)
