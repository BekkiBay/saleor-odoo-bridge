"""Odoo → domain маппинг для stock: warehouse slug + variant ref."""

from __future__ import annotations

import pytest

from saleor_bridge.adapters.odoo.stock import fetch_default_warehouse, fetch_variant_ref
from tests.stock_fakes import FakeOdoo


@pytest.mark.asyncio
async def test_default_warehouse_slug_is_unique():
    # slug = f"{slugify(code)}-{id}" — гарантия уникальности (подводные камни 3.3)
    odoo = FakeOdoo(warehouses=[{"id": 7, "name": "Главный склад", "code": "WH"}])
    wh = await fetch_default_warehouse(odoo)
    assert wh is not None
    assert wh.external_id == "7"
    assert wh.name == "Главный склад"
    assert wh.slug == "wh-7"


@pytest.mark.asyncio
async def test_default_warehouse_none_when_empty():
    assert await fetch_default_warehouse(FakeOdoo(warehouses=[])) is None


@pytest.mark.asyncio
async def test_variant_ref_maps_sku_and_template():
    odoo = FakeOdoo(variants={5: {"default_code": "SKU-005", "product_tmpl_id": [9, "Tmpl"]}})
    ref = await fetch_variant_ref(odoo, 5)
    assert ref == {"sku": "SKU-005", "template_id": 9}


@pytest.mark.asyncio
async def test_variant_ref_sku_fallback():
    odoo = FakeOdoo(variants={5: {"default_code": False, "product_tmpl_id": [9, "Tmpl"]}})
    ref = await fetch_variant_ref(odoo, 5)
    assert ref["sku"] == "odoo-5"


@pytest.mark.asyncio
async def test_variant_ref_missing_returns_none():
    assert await fetch_variant_ref(FakeOdoo(variants={}), 999) is None
