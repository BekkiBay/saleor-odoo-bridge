"""Integration-lite: sync_template_variants_to_saleor with FakeOdoo + respx.

A template with 2 variants (ColorxSize) → bulk-creates variants with the
correct attribute assignments and price; the dummy variant (from migration)
is deleted (ADR-0025).
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from saleor_bridge.adapters.odoo.binding import BindingRepository
from saleor_bridge.saleor.client import SaleorClient
from saleor_bridge.usecases.sync_template_variants_to_saleor import (
    sync_template_variants_to_saleor,
)
from tests.stock_fakes import FakeOdoo

_URL = "http://saleor.test/graphql/"
_CHANNEL = "Q2hhbm5lbDox"
_PRODUCT = "UHJvZHVjdDox"
_DUMMY = "VmFyaWFudDpkdW1teQ=="

_NEW_IDS = {"DRESS-001-S-RED": "VmFyaWFudDpT", "DRESS-001-M-RED": "VmFyaWFudDpN"}


def _router(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    q = body["query"]
    v = body.get("variables") or {}
    if "productVariantBulkCreate(" in q:
        results = [
            {"productVariant": {"id": _NEW_IDS[item["sku"]], "sku": item["sku"]}, "errors": []}
            for item in v["variants"]
        ]
        return httpx.Response(200, json={"data": {"productVariantBulkCreate": {
            "results": results, "errors": [],
        }}})
    if "productVariantDelete(" in q:
        return httpx.Response(200, json={"data": {"productVariantDelete": {
            "productVariant": {"id": v["id"]}, "errors": [],
        }}})
    if "product(id:$id)" in q:
        return httpx.Response(200, json={"data": {"product": {
            "id": _PRODUCT, "name": "Dress", "metafields": {},
            "variants": [{"id": _DUMMY, "sku": "DRESS-001"}],
        }}})
    raise AssertionError(f"unexpected Saleor query: {q[:80]}")


def _odoo() -> FakeOdoo:
    return FakeOdoo(
        variants={
            5: {"default_code": "DRESS-001-S-RED", "lst_price": 150000.0, "standard_price": 0.0,
                "barcode": False, "active": True, "product_tmpl_id": [1, "Dress"],
                "product_template_attribute_value_ids": [501, 502]},
            6: {"default_code": "DRESS-001-M-RED", "lst_price": 175000.0, "standard_price": 0.0,
                "barcode": False, "active": True, "product_tmpl_id": [1, "Dress"],
                "product_template_attribute_value_ids": [501, 503]},
        },
        ptavs={
            501: {"attribute_id": [10, "Color"], "product_attribute_value_id": [100, "Red"]},
            502: {"attribute_id": [11, "Size"], "product_attribute_value_id": [110, "S"]},
            503: {"attribute_id": [11, "Size"], "product_attribute_value_id": [111, "M"]},
        },
        bindings={
            ("product.template", 1): _PRODUCT,
            ("product.attribute", 10): "A_COLOR",
            ("product.attribute", 11): "A_SIZE",
            ("product.attribute.value", 100): "V_RED",
            ("product.attribute.value", 110): "V_S",
            ("product.attribute.value", 111): "V_M",
        },
    )


@respx.mock
@pytest.mark.asyncio
async def test_variant_generation_bulk_create_and_dummy_delete():
    route = respx.post(_URL).mock(side_effect=_router)
    odoo = _odoo()
    client = SaleorClient(api_url=_URL, app_token="t")

    res = await sync_template_variants_to_saleor(
        1, client, odoo, BindingRepository(odoo), channel_id=_CHANNEL
    )
    assert res.ok is True

    bodies = [json.loads(c.request.content) for c in route.calls]
    bulk = [b for b in bodies if "productVariantBulkCreate(" in b["query"]]
    assert len(bulk) == 1
    created = {item["sku"]: item for item in bulk[0]["variables"]["variants"]}
    assert set(created) == {"DRESS-001-S-RED", "DRESS-001-M-RED"}

    # S3: price in channelListings = lst_price (= list_price + price_extra)
    assert created["DRESS-001-S-RED"]["channelListings"] == [{"channelId": _CHANNEL, "price": "150000.00"}]
    assert created["DRESS-001-M-RED"]["channelListings"] == [{"channelId": _CHANNEL, "price": "175000.00"}]

    # attribute assignments in the BulkAttributeValueInput {id, dropdown:{id}} shape
    s_attrs = {a["id"]: a["dropdown"]["id"] for a in created["DRESS-001-S-RED"]["attributes"]}
    assert s_attrs == {"A_COLOR": "V_RED", "A_SIZE": "V_S"}

    # dummy deleted (ADR-0025)
    deletes = [b for b in bodies if "productVariantDelete(" in b["query"]]
    assert len(deletes) == 1
    assert deletes[0]["variables"]["id"] == _DUMMY

    # bindings created for both variants
    assert odoo.bindings[("product.product", 5)] == "VmFyaWFudDpT"
    assert odoo.bindings[("product.product", 6)] == "VmFyaWFudDpN"


@respx.mock
@pytest.mark.asyncio
async def test_empty_desired_does_not_touch_saleor():
    # S7 regression: a template with no active variants (data anomaly) must NOT delete
    # the working dummy variant in Saleor. Reconcile is a full no-op, zero Saleor calls.
    route = respx.post(_URL).mock(side_effect=_router)
    odoo = FakeOdoo(variants={}, bindings={("product.template", 99): _PRODUCT})
    client = SaleorClient(api_url=_URL, app_token="t")

    res = await sync_template_variants_to_saleor(
        99, client, odoo, BindingRepository(odoo), channel_id=_CHANNEL
    )
    assert res.ok is True
    assert len(route.calls) == 0  # Saleor untouched (no delete, no fetch)
