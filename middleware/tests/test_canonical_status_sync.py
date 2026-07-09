"""Canonical justix_status push: updateMetadata mutation + usecase."""
from __future__ import annotations

import pytest
import respx

from saleor_bridge.adapters.odoo.binding import BindingRepository
from saleor_bridge.adapters.saleor import order_mutations as om
from saleor_bridge.saleor.client import SaleorClient
from saleor_bridge.usecases.sync_canonical_status_to_saleor import (
    sync_canonical_status_to_saleor,
)
from tests.saleor_order_fakes import make_saleor_router, order_node
from tests.stock_fakes import FakeOdoo

_URL = "http://saleor.test/graphql/"
_OID = "T3JkZXI6MQ=="


def _client() -> SaleorClient:
    return SaleorClient(api_url=_URL, app_token="t")


@respx.mock
@pytest.mark.asyncio
async def test_update_order_metadata_sends_mutation():
    cap: list = []
    respx.post(_URL).mock(side_effect=make_saleor_router(order_node(), capture=cap))
    res = await om.update_order_metadata(_client(), _OID, {"justix_status": "shipped"})
    assert res.ok
    sent = [b for b in cap if "updateMetadata(" in b["query"]]
    assert len(sent) == 1
    assert sent[0]["variables"]["id"] == _OID
    assert sent[0]["variables"]["input"] == [{"key": "justix_status", "value": "shipped"}]


@respx.mock
@pytest.mark.asyncio
async def test_usecase_pushes_metadata_and_touches_binding():
    cap: list = []
    respx.post(_URL).mock(side_effect=make_saleor_router(order_node(), capture=cap))
    odoo = FakeOdoo(
        sale_orders={5: {"state": "sale", "name": "S5", "justix_status": "shipped"}},
        bindings={("sale.order", 5): _OID},
    )
    res = await sync_canonical_status_to_saleor(5, _client(), odoo, BindingRepository(odoo))
    assert res.ok
    sent = [b for b in cap if "updateMetadata(" in b["query"]]
    assert sent and sent[0]["variables"]["input"] == [{"key": "justix_status", "value": "shipped"}]
    assert any(m == "saleor.binding" and "last_sync_out" in vals for m, _ids, vals in odoo.writes)


@respx.mock
@pytest.mark.asyncio
async def test_usecase_skips_when_no_status():
    cap: list = []
    respx.post(_URL).mock(side_effect=make_saleor_router(order_node(), capture=cap))
    odoo = FakeOdoo(sale_orders={5: {"state": "draft", "name": "S5"}},  # no justix_status
                    bindings={("sale.order", 5): _OID})
    res = await sync_canonical_status_to_saleor(5, _client(), odoo, BindingRepository(odoo))
    assert res.ok and "no justix_status" in res.message
    assert cap == []


@respx.mock
@pytest.mark.asyncio
async def test_usecase_skips_when_no_binding():
    cap: list = []
    respx.post(_URL).mock(side_effect=make_saleor_router(order_node(), capture=cap))
    odoo = FakeOdoo(sale_orders={5: {"state": "sale", "name": "S5", "justix_status": "assembling"}})
    res = await sync_canonical_status_to_saleor(5, _client(), odoo, BindingRepository(odoo))
    assert res.ok and "no binding" in res.message
    assert cap == []
