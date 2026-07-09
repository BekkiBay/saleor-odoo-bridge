"""Token exchange endpoint — Saleor POSTs here after the App is installed.

Reference: https://docs.saleor.io/developer/extending/apps/installing-apps#token-exchange

Saleor sends `auth_token` in the body + `saleor-api-url` in the headers (or body).
The endpoint must be **idempotent** — Saleor may retry during install.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Header, Request, Response

from saleor_bridge.apl.base import AuthData
from saleor_bridge.apl.redis_apl import RedisAPL
from saleor_bridge.config import Settings, get_settings
from saleor_bridge.saleor.client import SaleorClient

log = structlog.get_logger()
router = APIRouter(tags=["register"])


async def _verify_app_token(api_url: str, token: str) -> bool:
    """Confirm `token` is a genuine Saleor App token for THIS Saleor before we store it.

    This is the auth gate for /api/register. The endpoint overwrites the stored Saleor
    app bearer token, so without a check any reachable POST could break sync (write a
    junk token) or inject a rogue one. A shared secret can't guard it — the manifest
    that declares tokenTargetUrl is public — but only a token Saleor actually issued
    authenticates `query { app { id } }` (an app may always introspect itself). So
    verifying the token against the configured Saleor IS the gate. Any error / null app
    → reject (fail closed): don't persist a token we couldn't confirm.
    """
    client = SaleorClient(api_url=api_url, app_token=token)
    try:
        body = await client.execute("query { app { id } }")
    except Exception as exc:  # noqa: BLE001 — fail closed on any verification error
        log.warning("register_token_verify_error", error=str(exc))
        return False
    app = (body.get("data") or {}).get("app") or {}
    return bool(app.get("id"))


@router.post("/register")
async def register(
    request: Request,
    response: Response,
    saleor_api_url: str | None = Header(None, alias="saleor-api-url"),
    saleor_domain: str | None = Header(None, alias="saleor-domain"),
    settings: Settings = Depends(get_settings),
) -> dict:
    body = await request.json()
    token = body.get("auth_token") or body.get("token") or ""
    # Key the APL by the CANONICAL settings.saleor_api_url, NOT by what Saleor
    # reported in the header/body: Saleor announces its public URL (often an
    # unreachable localhost:8000), while the worker/CLI talk to
    # settings.saleor_api_url (host.docker.internal:8000) — the token must be stored
    # under the same key, otherwise get_saleor_client won't find it. Same principle
    # as for JWKS in webhooks.py. We keep the actual announced URL in the log.
    announced = body.get("saleor_api_url") or saleor_api_url
    api_url = settings.saleor_api_url

    if not token:
        log.warning("register_missing_token", body_keys=list(body.keys()))
        return {"success": False, "error": "missing auth_token"}

    # Auth gate: only persist a token Saleor genuinely issued for this instance.
    if not await _verify_app_token(api_url, token):
        log.warning("register_token_invalid", announced_url=announced, domain=saleor_domain)
        response.status_code = 401
        return {"success": False, "error": "token verification failed"}

    apl = RedisAPL(settings.redis_url)
    try:
        auth = AuthData(
            saleor_api_url=api_url,
            token=token,
            app_id=body.get("app_id", ""),
            domain=saleor_domain or "",
        )
        # set — idempotent (overwrite is OK, Saleor may retry with the same or a new token).
        await apl.set(auth)
        log.info(
            "register_ok",
            saleor_api_url=api_url,
            announced_url=announced,
            domain=saleor_domain,
            token_len=len(token),
        )
    finally:
        await apl.aclose()

    return {"success": True}
