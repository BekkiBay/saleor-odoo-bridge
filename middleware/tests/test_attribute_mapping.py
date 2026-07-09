"""Odoo product.attribute / .value → domain.Attribute маппинг (Phase 3.5)."""

from __future__ import annotations

import pytest

from saleor_bridge.adapters.odoo.attribute import fetch_attribute, fetch_attribute_value
from tests.stock_fakes import FakeOdoo


def _odoo() -> FakeOdoo:
    return FakeOdoo(
        attributes={
            10: {"name": "Color", "create_variant": "always", "value_ids": [100, 101, 102]},
            20: {"name": "Material", "create_variant": "no_variant", "value_ids": [200]},
        },
        attribute_values={
            100: {"name": "Red", "html_color": "#ff0000", "attribute_id": [10, "Color"]},
            101: {"name": "Blue", "html_color": False, "attribute_id": [10, "Color"]},
            102: {"name": "Green", "html_color": False, "attribute_id": [10, "Color"]},
            200: {"name": "Cotton", "html_color": False, "attribute_id": [20, "Material"]},
        },
    )


@pytest.mark.asyncio
async def test_attribute_maps_name_and_values():
    attr = await fetch_attribute(_odoo(), 10)
    assert attr is not None
    assert attr.external_id == "10"
    assert attr.name == "Color"
    assert attr.input_type == "DROPDOWN"  # MVP per ADR-0027
    assert [v.name for v in attr.values] == ["Red", "Blue", "Green"]
    assert attr.values[0].external_id == "100"
    assert attr.values[0].color_hex == "#ff0000"
    assert attr.values[1].color_hex is None  # html_color False → None


@pytest.mark.asyncio
async def test_no_variant_attribute_skipped():
    # create_variant='no_variant' (материал/состав) — product-level, Phase 4 → None.
    assert await fetch_attribute(_odoo(), 20) is None


@pytest.mark.asyncio
async def test_attribute_missing_returns_none():
    assert await fetch_attribute(_odoo(), 999) is None


@pytest.mark.asyncio
async def test_attribute_value_resolves_parent():
    data = await fetch_attribute_value(_odoo(), 100)
    assert data is not None
    assert data["attribute_id"] == 10
    assert data["value"].name == "Red"
    assert data["value"].external_id == "100"


@pytest.mark.asyncio
async def test_attribute_value_missing_returns_none():
    assert await fetch_attribute_value(_odoo(), 999) is None
