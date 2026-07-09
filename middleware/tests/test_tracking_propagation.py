"""Tracking number из picking → OrderFulfillInput.trackingNumber (ADR-0019)."""

from __future__ import annotations

import pytest
import respx

from saleor_bridge.adapters.saleor import order_mutations as om
from saleor_bridge.saleor.client import SaleorClient
from tests.saleor_order_fakes import make_saleor_router, order_line, order_node

_URL = "http://saleor.test/graphql/"
_OID = "T3JkZXI6MQ=="
_WH = "V2FyZWhvdXNlOjE="


def _client() -> SaleorClient:
    return SaleorClient(api_url=_URL, app_token="t")


@respx.mock
@pytest.mark.asyncio
async def test_tracking_in_fulfill_input():
    cap: list = []
    node = order_node(status="UNFULFILLED", lines=[order_line("L1", "SKU-001", 2)])
    respx.post(_URL).mock(side_effect=make_saleor_router(node, capture=cap))
    res = await om.fulfill_order(
        _client(), _OID, sku_qty={"SKU-001": 2}, warehouse_id=_WH,
        tracking_number="TRACK-123", notify=True,
    )
    assert res.ok
    inp = next(b for b in cap if "orderFulfill(" in b["query"])["variables"]["input"]
    assert inp["trackingNumber"] == "TRACK-123"
    assert inp["notifyCustomer"] is True
    assert inp["allowStockToBeExceeded"] is False
    assert inp["lines"][0]["orderLineId"] == "L1"
    assert inp["lines"][0]["stocks"][0] == {"quantity": 2, "warehouse": _WH}


@respx.mock
@pytest.mark.asyncio
async def test_no_tracking_key_when_none():
    cap: list = []
    node = order_node(status="UNFULFILLED", lines=[order_line("L1", "SKU-001", 1)])
    respx.post(_URL).mock(side_effect=make_saleor_router(node, capture=cap))
    res = await om.fulfill_order(
        _client(), _OID, sku_qty={"SKU-001": 1}, warehouse_id=_WH, tracking_number=None,
    )
    assert res.ok
    inp = next(b for b in cap if "orderFulfill(" in b["query"])["variables"]["input"]
    assert "trackingNumber" not in inp
