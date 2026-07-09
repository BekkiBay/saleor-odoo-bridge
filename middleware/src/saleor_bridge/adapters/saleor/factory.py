"""Create an authenticated SaleorClient from the APL (token of the installed App).

The token is stored by the `/api/register` endpoint when the Saleor App is installed
(see the smoke flow and scripts/install_bridge_app.py). Fallback — env BRIDGE_SALEOR_APP_TOKEN.
"""

from __future__ import annotations

import structlog

from saleor_bridge.apl.redis_apl import RedisAPL
from saleor_bridge.config import Settings
from saleor_bridge.saleor.client import SaleorClient

log = structlog.get_logger()


class NoSaleorToken(RuntimeError):
    """No App token — the bridge-app needs to be installed (install_bridge_app.py)."""


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
            f"no Saleor App token for {settings.saleor_api_url} — install the bridge-app "
            f"(python scripts/install_bridge_app.py) or set BRIDGE_SALEOR_APP_TOKEN"
        )
    return SaleorClient(api_url=settings.saleor_api_url, app_token=token)
