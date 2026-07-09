"""Агрегация stock.quant → StockLevel (ADR-0015, ADR-0017)."""

from __future__ import annotations

import pytest

from saleor_bridge.adapters.odoo.stock import fetch_aggregated_stock
from saleor_bridge.domain.stock import Warehouse
from tests.stock_fakes import FakeOdoo

_WH = Warehouse(external_id="1", name="Main", slug="wh-1")


def _odoo(quants: list[float]) -> FakeOdoo:
    return FakeOdoo(
        variants={5: {"default_code": "SKU-005", "product_tmpl_id": [5, "X"]}},
        quants=[{"quantity": q, "product_id": [5, "X"]} for q in quants],
    )


@pytest.mark.asyncio
async def test_multiple_quants_summed():
    levels = await fetch_aggregated_stock(_odoo([10.0, 5.0, 3.0]), 5, _WH, safety_buffer=1)
    assert len(levels) == 1
    lvl = levels[0]
    assert lvl.variant_sku == "SKU-005"
    assert lvl.warehouse_external_id == "1"
    assert lvl.raw_quantity == 18
    assert lvl.available_quantity == 17


@pytest.mark.asyncio
async def test_single_quant():
    levels = await fetch_aggregated_stock(_odoo([20.0]), 5, _WH, safety_buffer=1)
    assert levels[0].raw_quantity == 20
    assert levels[0].display_quantity == 19


@pytest.mark.asyncio
async def test_no_quants_is_zero():
    levels = await fetch_aggregated_stock(_odoo([]), 5, _WH, safety_buffer=1)
    assert levels[0].raw_quantity == 0
    assert levels[0].available_quantity == 0


@pytest.mark.asyncio
async def test_fractional_quants_floored():
    # 2.9 + 1.4 = 4.3 → floor 4 (консервативно против оверселла)
    levels = await fetch_aggregated_stock(_odoo([2.9, 1.4]), 5, _WH, safety_buffer=0)
    assert levels[0].raw_quantity == 4
