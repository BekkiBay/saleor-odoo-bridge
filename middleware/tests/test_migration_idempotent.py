"""Idempotency of the single-variant product migration (S7, ADR-0025).

Reconciliation runs twice: the 1st pass adopts the dummy variant (creates the binding),
the 2nd finds the binding and only updates the price. No create/delete, no duplicates.
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
_PRODUCT = "UHJvZHVjdDo3"
_DUMMY = "VmFyaWFudDpkdW1teTc="


def _router(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    q = body["query"]
    if "product(id:$id)" in q:
        return httpx.Response(200, json={"data": {"product": {
            "id": _PRODUCT, "name": "Blouse", "metafields": {},
            "variants": [{"id": _DUMMY, "sku": "SKU-007"}],
        }}})
    if "productVariantChannelListingUpdate(" in q:
        return httpx.Response(200, json={"data": {"productVariantChannelListingUpdate": {"errors": []}}})
    raise AssertionError(f"unexpected Saleor query: {q[:80]}")


def _odoo() -> FakeOdoo:
    return FakeOdoo(
        variants={7: {"default_code": "SKU-007", "lst_price": 120000.0, "standard_price": 0.0,
                      "barcode": False, "active": True, "product_tmpl_id": [7, "Blouse"],
                      "product_template_attribute_value_ids": []}},
        bindings={("product.template", 7): _PRODUCT},
    )


@respx.mock
@pytest.mark.asyncio
async def test_migration_twice_no_duplicate():
    route = respx.post(_URL).mock(side_effect=_router)
    odoo = _odoo()
    client = SaleorClient(api_url=_URL, app_token="t")
    repo = BindingRepository(odoo)

    res1 = await sync_template_variants_to_saleor(7, client, odoo, repo, channel_id=_CHANNEL)
    res2 = await sync_template_variants_to_saleor(7, client, odoo, repo, channel_id=_CHANNEL)
    assert res1.ok and res2.ok

    bodies = [json.loads(c.request.content) for c in route.calls]
    # adopt path: NEITHER create NOR delete of variants
    assert not any("productVariantBulkCreate(" in b["query"] for b in bodies)
    assert not any("productVariantDelete(" in b["query"] for b in bodies)
    # price is pushed both times (idempotent re-push)
    assert sum("productVariantChannelListingUpdate(" in b["query"] for b in bodies) == 2

    # exactly one binding product.product:7 → dummy (no duplicates)
    assert odoo.bindings[("product.product", 7)] == _DUMMY
    variant_creates = [c for c in odoo.creates
                       if c[0] == "saleor.binding" and c[1].get("model_name") == "product.product"]
    assert len(variant_creates) == 1
