"""Integration-lite: sync_stock_to_saleor с FakeOdoo + respx-моканным Saleor.

Проверяем полный flow: variant→template binding → Saleor product → ensure warehouse
→ trackInventory=True → productVariantStocksUpdate с правильным quantity (raw - buffer).
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from saleor_bridge.adapters.odoo.binding import BindingRepository
from saleor_bridge.saleor.client import SaleorClient
from saleor_bridge.usecases.sync_stock_to_saleor import (
    CatalogBindingMissing,
    sync_stock_to_saleor,
)
from tests.stock_fakes import FakeOdoo

_URL = "http://saleor.test/graphql/"
_PRODUCT_ID = "UHJvZHVjdDox"
_VARIANT_ID = "UHJvZHVjdFZhcmlhbnQ6MQ=="
_WAREHOUSE_ID = "V2FyZWhvdXNlOjE="


def _saleor_router(request: httpx.Request) -> httpx.Response:
    q = json.loads(request.content)["query"]
    if "warehouses(first:100)" in q:
        return httpx.Response(200, json={"data": {"warehouses": {"edges": [
            {"node": {"id": _WAREHOUSE_ID, "slug": "default-warehouse", "name": "Default"}}
        ]}}})
    if "product(id:$id)" in q:
        return httpx.Response(200, json={"data": {"product": {
            "id": _PRODUCT_ID, "name": "Тест", "metafields": {},
            "variants": [{"id": _VARIANT_ID, "sku": "SKU-005"}],
        }}})
    if "productVariantStocksUpdate(" in q:
        return httpx.Response(200, json={"data": {"productVariantStocksUpdate": {
            "productVariant": {"id": _VARIANT_ID}, "errors": [],
        }}})
    if "productVariantUpdate(" in q:
        return httpx.Response(200, json={"data": {"productVariantUpdate": {
            "productVariant": {"id": _VARIANT_ID, "trackInventory": True}, "errors": [],
        }}})
    raise AssertionError(f"unexpected Saleor query: {q[:80]}")


def _odoo() -> FakeOdoo:
    return FakeOdoo(
        variants={5: {"default_code": "SKU-005", "product_tmpl_id": [5, "Тест"]}},
        quants=[{"quantity": 20.0, "product_id": [5, "Тест"]}],
        warehouses=[{"id": 1, "name": "Main", "code": "WH"}],
        bindings={("product.template", 5): _PRODUCT_ID},
    )


@respx.mock
@pytest.mark.asyncio
async def test_stock_sync_pushes_buffered_quantity():
    route = respx.post(_URL).mock(side_effect=_saleor_router)
    odoo = _odoo()
    client = SaleorClient(api_url=_URL, app_token="t")

    res = await sync_stock_to_saleor(5, client, odoo, BindingRepository(odoo), safety_buffer=1)

    assert res.ok is True
    assert res.odoo_id == 5  # template id

    bodies = [json.loads(c.request.content) for c in route.calls]
    # productVariantStocksUpdate ушёл с quantity = 20 - 1 = 19, на нужный warehouse/variant
    stock_calls = [b for b in bodies if "productVariantStocksUpdate(" in b["query"]]
    assert len(stock_calls) == 1
    v = stock_calls[0]["variables"]
    assert v["variantId"] == _VARIANT_ID
    assert v["stocks"] == [{"warehouse": _WAREHOUSE_ID, "quantity": 19}]

    # trackInventory=True выставлен
    track_calls = [b for b in bodies if "productVariantUpdate(" in b["query"]]
    assert len(track_calls) == 1
    assert track_calls[0]["variables"]["input"]["trackInventory"] is True

    # warehouse binding создан, last_sync_out обновлён
    assert any(m == "saleor.binding" and vals.get("model_name") == "stock.warehouse"
               for m, vals in odoo.creates)
    assert any(m == "saleor.binding" and "last_sync_out" in vals for m, _ids, vals in odoo.writes)


@respx.mock
@pytest.mark.asyncio
async def test_missing_catalog_binding_raises_for_retry():
    respx.post(_URL).mock(side_effect=_saleor_router)
    odoo = _odoo()
    odoo.bindings = {}  # каталог ещё не синкнул товар
    client = SaleorClient(api_url=_URL, app_token="t")

    with pytest.raises(CatalogBindingMissing):
        await sync_stock_to_saleor(5, client, odoo, BindingRepository(odoo), safety_buffer=1)
