"""Odoo product.product + PTAV → domain.Variant маппинг (Phase 3.5, ADR-0024/0026)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from saleor_bridge.adapters.odoo.variant import fetch_variant, fetch_variants_for_template
from tests.stock_fakes import FakeOdoo


def _odoo() -> FakeOdoo:
    return FakeOdoo(
        variants={
            5: {
                "default_code": "DRESS-001-M-RED",
                "lst_price": 150000.0,
                "standard_price": 80000.0,
                "barcode": "4600000000015",
                "active": True,
                "product_tmpl_id": [1, "Платье"],
                "product_template_attribute_value_ids": [501, 502],
            },
            6: {
                "default_code": False,  # пустой → fallback odoo-<id>
                "lst_price": 150000.0,
                "standard_price": 0.0,
                "barcode": False,
                "active": True,
                "product_tmpl_id": [1, "Платье"],
                "product_template_attribute_value_ids": [503, 502],
            },
        },
        ptavs={
            501: {"attribute_id": [10, "Color"], "product_attribute_value_id": [100, "Red"]},
            502: {"attribute_id": [11, "Size"], "product_attribute_value_id": [110, "M"]},
            503: {"attribute_id": [10, "Color"], "product_attribute_value_id": [101, "Blue"]},
        },
    )


@pytest.mark.asyncio
async def test_variant_maps_sku_price_attributes():
    v = await fetch_variant(_odoo(), 5)
    assert v is not None
    assert v.external_id == "5"
    assert v.template_external_id == "1"
    assert v.sku == "DRESS-001-M-RED"
    assert v.price == Decimal("150000.00")  # lst_price (= list_price + price_extra, ADR-0026)
    assert v.cost == Decimal("80000.00")
    assert v.barcode == "4600000000015"
    assert v.active is True
    # PTAV → (attribute, value) пары через product_attribute_value_id
    pairs = {(a.attribute_external_id, a.value_external_id) for a in v.attributes}
    assert pairs == {("10", "100"), ("11", "110")}


@pytest.mark.asyncio
async def test_variant_sku_fallback_and_empty_barcode():
    v = await fetch_variant(_odoo(), 6)
    assert v.sku == "odoo-6"
    assert v.barcode is None


@pytest.mark.asyncio
async def test_variant_missing_returns_none():
    assert await fetch_variant(_odoo(), 999) is None


@pytest.mark.asyncio
async def test_fetch_variants_for_template_batches():
    variants = await fetch_variants_for_template(_odoo(), 1)
    assert {v.external_id for v in variants} == {"5", "6"}
    by_id = {v.external_id: v for v in variants}
    assert {(a.attribute_external_id, a.value_external_id) for a in by_id["6"].attributes} == {
        ("10", "101"), ("11", "110")
    }
