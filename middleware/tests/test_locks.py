"""odoo_record_lock — no-op without a redis_url (hardening)."""

from __future__ import annotations

import pytest

from saleor_bridge.locks import odoo_record_lock


@pytest.mark.asyncio
async def test_lock_noop_without_redis_url():
    ran = False
    async with odoo_record_lock(None, "product.category:1"):
        ran = True
    assert ran  # body executed, no error without redis


@pytest.mark.asyncio
async def test_lock_noop_empty_url():
    async with odoo_record_lock("", "product.template:5"):
        pass  # does not raise
