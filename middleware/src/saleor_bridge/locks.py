"""Per-record distributed lock (Redis SETNX) — против гонок одновременного create.

Сценарий: категория создаётся своим webhook-job'ом И рекурсивным ensure-parent
из job'а ребёнка → оба видят «binding нет» → оба создают дубль. Лок по
(model, odoo_id) сериализует критическую секцию check-or-create.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import redis.asyncio as redis


@asynccontextmanager
async def odoo_record_lock(redis_url: str | None, key: str, *, ttl: int = 30, wait: float = 10.0):
    """Лок saleor_bridge:lock:<key>. redis_url=None → no-op (тесты/без redis).

    Если за `wait` сек лок не взят — продолжаем без него (binding-проверка всё
    равно идемпотентна, плюс есть partial-unique backstop в Odoo).
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
            try:
                await client.delete(lock_key)
            except Exception:  # noqa: BLE001
                pass
        await client.aclose()
