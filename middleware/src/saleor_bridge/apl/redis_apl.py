"""Redis-based APL — a simple implementation without TTL (tokens are long-lived)."""

from __future__ import annotations

import json

import redis.asyncio as redis

from saleor_bridge.apl.base import APL, AuthData


def _key(saleor_api_url: str) -> str:
    return f"saleor_bridge:apl:{saleor_api_url}"


class RedisAPL(APL):
    def __init__(self, redis_url: str) -> None:
        self._client = redis.from_url(redis_url, decode_responses=True)

    async def get(self, saleor_api_url: str) -> AuthData | None:
        raw = await self._client.get(_key(saleor_api_url))
        if not raw:
            return None
        data = json.loads(raw)
        return AuthData(**data)

    async def set(self, auth: AuthData) -> None:
        await self._client.set(_key(auth.saleor_api_url), json.dumps(auth.__dict__))

    async def delete(self, saleor_api_url: str) -> None:
        await self._client.delete(_key(saleor_api_url))

    async def list_all(self) -> list[AuthData]:
        keys: list[str] = []
        async for key in self._client.scan_iter("saleor_bridge:apl:*"):
            keys.append(key)
        if not keys:
            return []
        values = await self._client.mget(keys)
        out: list[AuthData] = []
        for v in values:
            if v:
                out.append(AuthData(**json.loads(v)))
        return out

    async def aclose(self) -> None:
        await self._client.aclose()
