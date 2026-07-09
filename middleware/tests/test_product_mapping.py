"""Odoo product.template row → domain.Product + Saleor input helpers."""

from __future__ import annotations

import json
from decimal import Decimal

from saleor_bridge.adapters.odoo.product import row_to_product
from saleor_bridge.adapters.saleor.product_mutations import (
    description_to_editorjs,
    metadata_list,
)


def _row(**over):
    base = {
        "id": 7,
        "name": "Блузка шёлковая розовая",
        "default_code": "SKU-007",
        "categ_id": [10, "Одежда / Блузки"],
        "list_price": 420000.0,
        "standard_price": 210000.0,
        "barcode": "4780000000007",
        "description_sale": "Нежная блузка",
        "active": True,
        "write_date": "2026-05-23 10:00:00",
    }
    base.update(over)
    return base


def test_product_basic_mapping():
    p = row_to_product(_row())
    assert p.external_id == "7"
    assert p.sku == "SKU-007"
    assert p.name == "Блузка шёлковая розовая"
    assert p.category_external_id == "10"
    assert p.list_price == Decimal("420000.00")
    assert p.cost_price == Decimal("210000.00")
    assert p.barcode == "4780000000007"
    assert p.description == "Нежная блузка"
    assert p.active is True
    assert p.write_date == "2026-05-23 10:00:00"


def test_price_rounds_to_two_decimals():
    p = row_to_product(_row(list_price=199999.999))
    assert p.list_price == Decimal("200000.00")


def test_missing_sku_falls_back_to_odoo_id():
    p = row_to_product(_row(default_code=False))
    assert p.sku == "odoo-7"


def test_inactive_and_empty_optional_fields():
    p = row_to_product(_row(active=False, barcode=False, description_sale=False))
    assert p.active is False
    assert p.barcode is None
    assert p.description is None


def test_description_to_editorjs_roundtrip():
    out = description_to_editorjs("hello")
    doc = json.loads(out)
    assert doc["blocks"][0]["data"]["text"] == "hello"
    assert description_to_editorjs(None) is None
    assert description_to_editorjs("") is None


def test_metadata_list_shape():
    assert metadata_list({"odoo_id": "7"}) == [{"key": "odoo_id", "value": "7"}]
