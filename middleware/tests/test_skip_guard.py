"""Skip-guard (ADR-0020): Odoo writes carry a saleor_sync_skip context."""

from __future__ import annotations

import pytest

from saleor_bridge.adapters.odoo import sale_order as so
from tests.stock_fakes import FakeOdoo

_SKIP = {"saleor_sync_skip": True}


@pytest.mark.asyncio
async def test_confirm_passes_skip_context():
    odoo = FakeOdoo(sale_orders={5: {"state": "draft", "name": "S5"}})
    await so.confirm_order(odoo, 5)
    confirm = [c for c in odoo.calls if c[1] == "action_confirm"]
    assert len(confirm) == 1
    assert confirm[0][2].get("context") == _SKIP


@pytest.mark.asyncio
async def test_cancel_passes_skip_context():
    odoo = FakeOdoo(sale_orders={5: {"state": "sale", "name": "S5"}})
    await so.cancel_order(odoo, 5)
    cancel = [c for c in odoo.calls if c[1] == "action_cancel"]
    assert len(cancel) == 1
    assert cancel[0][2].get("context") == _SKIP


@pytest.mark.asyncio
async def test_confirm_idempotent_no_call_when_already_sale():
    odoo = FakeOdoo(sale_orders={5: {"state": "sale", "name": "S5"}})
    await so.confirm_order(odoo, 5)
    assert [c for c in odoo.calls if c[1] == "action_confirm"] == []


@pytest.mark.asyncio
async def test_create_draft_passes_skip_context():
    odoo = FakeOdoo()
    from saleor_bridge.domain.order import Order
    order = Order(external_id="T2xk", external_number="42", customer_email="a@b.co", lines=[])
    await so.create_draft_order(odoo, order, partner_id=1, invoice_id=1, shipping_id=1)
    creates = [c for c in odoo.calls if c[1] == "create"]
    assert len(creates) == 1
    assert creates[0][2].get("context") == _SKIP
