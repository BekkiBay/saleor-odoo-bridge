"""arq Redis pool helper for enqueueing from FastAPI."""

from __future__ import annotations

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings


async def make_arq_pool(redis_url: str) -> ArqRedis:
    return await create_pool(RedisSettings.from_dsn(redis_url))
