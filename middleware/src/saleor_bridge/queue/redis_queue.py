"""Минимальная очередь на Redis Streams для webhook ack.

В Phase 3.0 — заглушка. Реальные consumers начинаются в Phase 3.1.

Паттерн: webhook handler делает `enqueue(event_type, payload)` → возвращает 200
в Saleor за <100ms. Background worker (отдельный процесс или asyncio task) читает
stream и обрабатывает.
"""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as redis
import structlog

log = structlog.get_logger()

STREAM_NAME = "saleor_bridge:webhooks"
MAX_LEN = 10_000  # capped stream — старые событий вытесняются


class WebhookQueue:
    def __init__(self, redis_url: str) -> None:
        self._client = redis.from_url(redis_url, decode_responses=True)

    async def enqueue(self, event_type: str, payload: dict[str, Any], trace_id: str) -> str:
        """Добавить event в stream. Возвращает Redis stream ID."""
        fields = {
            "event_type": event_type,
            "trace_id": trace_id,
            "payload": json.dumps(payload, ensure_ascii=False),
        }
        msg_id = await self._client.xadd(STREAM_NAME, fields, maxlen=MAX_LEN, approximate=True)
        log.info("webhook_enqueued", event_type=event_type, trace_id=trace_id, stream_id=msg_id)
        return str(msg_id)

    async def queue_depth(self) -> int:
        return int(await self._client.xlen(STREAM_NAME))

    async def aclose(self) -> None:
        await self._client.aclose()
