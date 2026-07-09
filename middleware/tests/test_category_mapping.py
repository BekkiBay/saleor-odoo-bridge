"""Odoo product.category row → domain.ProductCategory."""

from __future__ import annotations

from saleor_bridge.adapters.odoo.category import row_to_category
from saleor_bridge.adapters.saleor.slug import slugify


def test_nested_category():
    row = {
        "id": 5,
        "name": "Головные уборы",
        "parent_id": [4, "Аксессуары"],
        "complete_name": "Аксессуары / Головные уборы",
    }
    cat = row_to_category(row)
    assert cat.external_id == "5"
    assert cat.name == "Головные уборы"
    assert cat.parent_external_id == "4"
    assert cat.complete_name == "Аксессуары / Головные уборы"
    assert slugify(cat.complete_name) == "aksessuary-golovnye-ubory"


def test_root_category_no_parent():
    row = {"id": 4, "name": "Аксессуары", "parent_id": False, "complete_name": "Аксессуары"}
    cat = row_to_category(row)
    assert cat.parent_external_id is None
    assert cat.complete_name == "Аксессуары"


def test_complete_name_fallback_to_name():
    row = {"id": 9, "name": "Обувь", "parent_id": False}
    cat = row_to_category(row)
    assert cat.complete_name == "Обувь"
