"""Idempotency key + dedup tests (fakeredis-free, using fake client)."""

from __future__ import annotations

import pytest

from saleor_bridge.queue.idempotency import already_processed, make_key, release


def test_make_key_stable():
    k1 = make_key("ORDER_CREATED", "T3JkZXI6MQ==", {"event": "order_created"})
    k2 = make_key("ORDER_CREATED", "T3JkZXI6MQ==", {"event": "order_created"})
    assert k1 == k2
    assert k1.startswith("saleor_bridge:idem:")


def test_make_key_differs_by_event():
    k1 = make_key("ORDER_CREATED", "X", None)
    k2 = make_key("ORDER_FULLY_PAID", "X", None)
    assert k1 != k2


class _FakeRedis:
    """Минимальный fake: SET NX semantics."""

    def __init__(self):
        self.store: dict[str, str] = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def delete(self, key):
        self.store.pop(key, None)


@pytest.mark.asyncio
async def test_first_call_not_duplicate_second_is():
    client = _FakeRedis()
    key = make_key("ORDER_CREATED", "T3JkZXI6MQ==", None)

    first = await already_processed(client, key)
    second = await already_processed(client, key)

    assert first is False   # первый раз — новый
    assert second is True   # второй раз — duplicate


@pytest.mark.asyncio
async def test_release_allows_reprocess():
    # On enqueue failure the webhook releases the claim so Saleor's retry re-processes
    # (mark-before-enqueue → lost-on-queue-failure fix).
    client = _FakeRedis()
    key = make_key("ORDER_CREATED", "R", None)

    assert await already_processed(client, key) is False  # claimed
    assert await already_processed(client, key) is True   # duplicate blocked
    await release(client, key)
    assert await already_processed(client, key) is False  # released → fresh claim
