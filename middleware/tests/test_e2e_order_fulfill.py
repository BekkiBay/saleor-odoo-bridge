"""E2E: sync_picking_to_saleor — picking done → orderFulfill (FakeOdoo + respx)."""

from __future__ import annotations

import pytest
import respx

from saleor_bridge.adapters.odoo.binding import BindingRepository
from saleor_bridge.saleor.client import SaleorClient
from saleor_bridge.usecases.sync_order_status_to_saleor import sync_picking_to_saleor
from tests.saleor_order_fakes import make_saleor_router, order_line, order_node
from tests.stock_fakes import FakeOdoo

_URL = "http://saleor.test/graphql/"
_OID = "T3JkZXI6MQ=="


def _client() -> SaleorClient:
    return SaleorClient(api_url=_URL, app_token="t")


def _odoo() -> FakeOdoo:
    return FakeOdoo(
        pickings={9: {"state": "done", "sale_id": [5, "S5"],
                      "carrier_tracking_ref": "TRACK-9", "move_line_ids": [100]}},
        move_lines={100: {"product_id": [1, "P"], "quantity": 2.0}},
        variants={1: {"default_code": "SKU-001", "product_tmpl_id": [1, "T"]}},
        warehouses=[{"id": 1, "name": "Main", "code": "WH"}],
        bindings={("sale.order", 5): _OID},
    )


@respx.mock
@pytest.mark.asyncio
async def test_fulfill_flow_maps_lines_and_tracking():
    cap: list = []
    node = order_node(status="UNFULFILLED", lines=[order_line("L1", "SKU-001", 2)])
    respx.post(_URL).mock(side_effect=make_saleor_router(node, capture=cap))
    res = await sync_picking_to_saleor(9, _client(), _odoo(), BindingRepository(_odoo()))
    assert res.ok
    inp = next(b for b in cap if "orderFulfill(" in b["query"])["variables"]["input"]
    assert inp["trackingNumber"] == "TRACK-9"
    assert inp["lines"][0]["orderLineId"] == "L1"
    assert inp["lines"][0]["stocks"][0]["quantity"] == 2


@respx.mock
@pytest.mark.asyncio
async def test_picking_not_done_is_noop():
    cap: list = []
    respx.post(_URL).mock(side_effect=make_saleor_router(order_node(), capture=cap))
    odoo = FakeOdoo(pickings={9: {"state": "assigned", "sale_id": [5, "S5"],
                                  "carrier_tracking_ref": False, "move_line_ids": []}})
    res = await sync_picking_to_saleor(9, _client(), odoo, BindingRepository(odoo))
    assert res.ok and "no-op" in res.message
    assert cap == []
