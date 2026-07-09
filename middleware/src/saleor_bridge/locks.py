"""Per-record distributed lock (Redis SETNX) — guards against concurrent-create races.

Scenario: a category is created by its own webhook job AND by the recursive
ensure-parent call from a child job → both see "no binding" → both create a
duplicate. Locking on (model, odoo_id) serializes the check-or-create critical section.
"""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager

import redis.asyncio as redis


@asynccontextmanager
async def odoo_record_lock(redis_url: str | None, key: str, *, ttl: int = 30, wait: float = 10.0):
    """Lock saleor_bridge:lock:<key>. redis_url=None → no-op (tests/without redis).

    If the lock isn't acquired within `wait` seconds, we proceed without it
    (the binding check is idempotent anyway, plus there's a partial-unique
    backstop in Odoo).
    """
    if not redis_url:
        yield
        return
    client = redis.from_url(redis_url, decode_responses=True)
    lock_key = f"saleor_bridge:lock:{key}"
    acquired = False
    loop = asyncio.get_event_loop()
    deadline = loop.time() + wait
    try:
        while True:
            if await client.set(lock_key, "1", nx=True, ex=ttl):
                acquired = True
                break
            if loop.time() >= deadline:
                break
            await asyncio.sleep(0.2)
        yield
    finally:
        if acquired:
            with contextlib.suppress(Exception):
                await client.delete(lock_key)
        await client.aclose()
