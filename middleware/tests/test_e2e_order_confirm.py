"""E2E: sync_order_state_to_saleor — FakeOdoo + respx Saleor (confirm/cancel)."""

from __future__ import annotations

import pytest
import respx

from saleor_bridge.adapters.odoo.binding import BindingRepository
from saleor_bridge.saleor.client import SaleorClient
from saleor_bridge.usecases.sync_order_status_to_saleor import sync_order_state_to_saleor
from tests.saleor_order_fakes import make_saleor_router, order_node
from tests.stock_fakes import FakeOdoo

_URL = "http://saleor.test/graphql/"
_OID = "T3JkZXI6MQ=="


def _client() -> SaleorClient:
    return SaleorClient(api_url=_URL, app_token="t")


@respx.mock
@pytest.mark.asyncio
async def test_confirm_flow_pushes_orderConfirm_and_touches_binding():
    cap: list = []
    respx.post(_URL).mock(side_effect=make_saleor_router(order_node(status="UNCONFIRMED"), capture=cap))
    odoo = FakeOdoo(sale_orders={5: {"state": "sale", "name": "S00005"}},
                    bindings={("sale.order", 5): _OID})
    res = await sync_order_state_to_saleor(5, _client(), odoo, BindingRepository(odoo))
    assert res.ok
    assert any("orderConfirm(" in b["query"] for b in cap)
    assert any(m == "saleor.binding" and "last_sync_out" in vals for m, _ids, vals in odoo.writes)


@respx.mock
@pytest.mark.asyncio
async def test_cancel_flow_pushes_orderCancel():
    cap: list = []
    respx.post(_URL).mock(side_effect=make_saleor_router(order_node(status="UNFULFILLED"), capture=cap))
    odoo = FakeOdoo(sale_orders={5: {"state": "cancel", "name": "S5"}},
                    bindings={("sale.order", 5): _OID})
    res = await sync_order_state_to_saleor(5, _client(), odoo, BindingRepository(odoo))
    assert res.ok
    assert any("orderCancel(" in b["query"] for b in cap)


@respx.mock
@pytest.mark.asyncio
async def test_no_binding_skips_without_saleor_calls():
    cap: list = []
    respx.post(_URL).mock(side_effect=make_saleor_router(order_node(), capture=cap))
    odoo = FakeOdoo(sale_orders={5: {"state": "sale", "name": "S5"}})  # no binding
    res = await sync_order_state_to_saleor(5, _client(), odoo, BindingRepository(odoo))
    assert res.ok and "no saleor binding" in res.message
    assert cap == []


@respx.mock
@pytest.mark.asyncio
async def test_draft_state_is_noop():
    cap: list = []
    respx.post(_URL).mock(side_effect=make_saleor_router(order_node(), capture=cap))
    odoo = FakeOdoo(sale_orders={5: {"state": "draft", "name": "S5"}},
                    bindings={("sale.order", 5): _OID})
    res = await sync_order_state_to_saleor(5, _client(), odoo, BindingRepository(odoo))
    assert res.ok and "no-op" in res.message
    assert cap == []
