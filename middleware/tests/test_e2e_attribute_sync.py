"""Integration-lite: sync_attribute_to_saleor с FakeOdoo + respx Saleor (Phase 3.5, S1).

Полный flow: attributeCreate → attributeValueCreate×3 → hasVariants=True → assign.
Проверяем bindings (attribute + 3 values) и форму мутаций.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from saleor_bridge.adapters.odoo.binding import BindingRepository
from saleor_bridge.saleor.client import SaleorClient
from saleor_bridge.usecases.sync_attribute_to_saleor import sync_attribute_to_saleor
from tests.stock_fakes import FakeOdoo

_URL = "http://saleor.test/graphql/"
_PT = "UHJvZHVjdFR5cGU6MQ=="
_ATTR_ID = "QXR0cmlidXRlOjQy"
_VALUE_IDS = {"Red": "VmFsdWU6MQ==", "Blue": "VmFsdWU6Mg==", "Green": "VmFsdWU6Mw=="}


def _router(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    q = body["query"]
    v = body.get("variables") or {}
    if "attributeValueCreate(" in q:
        name = v["input"]["name"]
        return httpx.Response(200, json={"data": {"attributeValueCreate": {
            "attributeValue": {"id": _VALUE_IDS[name], "name": name, "slug": name.lower()},
            "errors": [],
        }}})
    if "attributeCreate(" in q:
        return httpx.Response(200, json={"data": {"attributeCreate": {
            "attribute": {"id": _ATTR_ID, "name": "Color", "slug": "color"}, "errors": [],
        }}})
    if "productAttributeAssign(" in q:
        return httpx.Response(200, json={"data": {"productAttributeAssign": {
            "productType": {"id": _PT}, "errors": [],
        }}})
    if "productTypeUpdate(" in q:
        return httpx.Response(200, json={"data": {"productTypeUpdate": {
            "productType": {"id": _PT, "hasVariants": True}, "errors": [],
        }}})
    if "productType(id:$id)" in q:
        return httpx.Response(200, json={"data": {"productType": {
            "id": _PT, "hasVariants": False, "variantAttributes": [],
        }}})
    if "attributes(first:100, filter:{search:$search})" in q:
        return httpx.Response(200, json={"data": {"attributes": {"edges": []}}})
    if "choices(first:100)" in q:
        return httpx.Response(200, json={"data": {"attribute": {"id": _ATTR_ID, "choices": {"edges": []}}}})
    raise AssertionError(f"unexpected Saleor query: {q[:80]}")


def _odoo() -> FakeOdoo:
    return FakeOdoo(
        attributes={42: {"name": "Color", "create_variant": "always", "value_ids": [1, 2, 3]}},
        attribute_values={
            1: {"name": "Red", "html_color": False, "attribute_id": [42, "Color"]},
            2: {"name": "Blue", "html_color": False, "attribute_id": [42, "Color"]},
            3: {"name": "Green", "html_color": False, "attribute_id": [42, "Color"]},
        },
    )


@respx.mock
@pytest.mark.asyncio
async def test_attribute_sync_creates_attribute_values_and_assigns():
    route = respx.post(_URL).mock(side_effect=_router)
    odoo = _odoo()
    client = SaleorClient(api_url=_URL, app_token="t")

    res = await sync_attribute_to_saleor(
        42, client, odoo, BindingRepository(odoo), product_type_id=_PT, model="product.attribute"
    )
    assert res.ok is True

    bodies = [json.loads(c.request.content) for c in route.calls]
    # attribute создан как PRODUCT/DROPDOWN
    create = [b for b in bodies if "attributeCreate(" in b["query"]]
    assert len(create) == 1
    assert create[0]["variables"]["input"]["type"] == "PRODUCT_TYPE"
    assert create[0]["variables"]["input"]["inputType"] == "DROPDOWN"
    # 3 значения созданы
    assert sum("attributeValueCreate(" in b["query"] for b in bodies) == 3
    # hasVariants включён + атрибут назначен как VARIANT
    assert any("productTypeUpdate(" in b["query"] for b in bodies)
    assign = [b for b in bodies if "productAttributeAssign(" in b["query"]]
    assert assign[0]["variables"]["operations"][0]["type"] == "VARIANT"

    # bindings: attribute + 3 values
    assert odoo.bindings[("product.attribute", 42)] == _ATTR_ID
    assert odoo.bindings[("product.attribute.value", 1)] == _VALUE_IDS["Red"]
    assert odoo.bindings[("product.attribute.value", 2)] == _VALUE_IDS["Blue"]
    assert odoo.bindings[("product.attribute.value", 3)] == _VALUE_IDS["Green"]


@respx.mock
@pytest.mark.asyncio
async def test_attribute_value_event_syncs_parent():
    respx.post(_URL).mock(side_effect=_router)
    odoo = _odoo()
    client = SaleorClient(api_url=_URL, app_token="t")
    # событие на значении (id=2) → синкается родительский атрибут (id=42)
    res = await sync_attribute_to_saleor(
        2, client, odoo, BindingRepository(odoo), product_type_id=_PT, model="product.attribute.value"
    )
    assert res.ok is True
    assert odoo.bindings[("product.attribute", 42)] == _ATTR_ID
