"""Negative stock in Odoo → 0 in Saleor (hardening S3, ADR-0016)."""

from __future__ import annotations

import pytest

from saleor_bridge.adapters.odoo.stock import fetch_aggregated_stock
from saleor_bridge.domain.stock import StockLevel, Warehouse
from tests.stock_fakes import FakeOdoo

_WH = Warehouse(external_id="1", name="Main", slug="wh-1")


@pytest.mark.parametrize("buffer", [0, 1, 5])
def test_negative_raw_clamps_to_zero(buffer):
    lvl = StockLevel(variant_sku="X", warehouse_external_id="1", raw_quantity=-3, safety_buffer=buffer)
    assert lvl.available_quantity == 0
    assert lvl.display_quantity == 0


@pytest.mark.asyncio
async def test_aggregate_negative_clamps_on_push():
    odoo = FakeOdoo(
        variants={5: {"default_code": "SKU-005", "product_tmpl_id": [5, "X"]}},
        quants=[{"quantity": -3.0, "product_id": [5, "X"]}],
    )
    levels = await fetch_aggregated_stock(odoo, 5, _WH, safety_buffer=1)
    assert levels[0].raw_quantity == -3   # raw value preserved
    assert levels[0].display_quantity == 0  # 0 goes to Saleor, not an error


@pytest.mark.asyncio
async def test_mixed_quants_net_negative():
    odoo = FakeOdoo(
        variants={5: {"default_code": "SKU-005", "product_tmpl_id": [5, "X"]}},
        quants=[{"quantity": 2.0, "product_id": [5, "X"]}, {"quantity": -5.0, "product_id": [5, "X"]}],
    )
    levels = await fetch_aggregated_stock(odoo, 5, _WH, safety_buffer=1)
    assert levels[0].raw_quantity == -3
    assert levels[0].display_quantity == 0
