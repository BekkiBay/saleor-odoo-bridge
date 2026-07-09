"""Idempotency guard via Redis SET NX with a TTL (ADR / spec: 24h)."""

from __future__ import annotations

import hashlib
import json

import redis.asyncio as redis

_TTL_SECONDS = 24 * 3600


def make_key(event_type: str, saleor_id: str, relevant: dict | None = None) -> str:
    raw = json.dumps(
        {"e": event_type, "id": saleor_id, "r": relevant or {}},
        sort_keys=True, ensure_ascii=False,
    )
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return f"saleor_bridge:idem:{digest}"


async def already_processed(client: redis.Redis, key: str) -> bool:
    """SET NX: returns True if the key already existed (i.e. duplicate)."""
    # set returns True if set (new), None if already exists.
    was_set = await client.set(key, "1", nx=True, ex=_TTL_SECONDS)
    return was_set is None


async def release(client: redis.Redis, key: str) -> None:
    """Undo an already_processed() claim so the event can be re-processed.

    Called when enqueue fails AFTER we claimed the key: without this the 24h dedup
    TTL swallows the event forever and Saleor's retry is silently skipped as a
    'duplicate' (mark-before-enqueue → lost-on-queue-failure bug)."""
    await client.delete(key)
