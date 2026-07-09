"""Integration-lite: create_category with respx-mocked Saleor (slug-collision retry)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from saleor_bridge.adapters.saleor.category_mutations import create_category
from saleor_bridge.saleor.client import SaleorClient

_URL = "http://saleor.test/graphql/"


def _slug_conflict() -> httpx.Response:
    return httpx.Response(200, json={"data": {"categoryCreate": {
        "category": None,
        "errors": [{"field": "slug", "message": "already exists", "code": "UNIQUE"}],
    }}})


def _created(saleor_id: str, slug: str) -> httpx.Response:
    return httpx.Response(200, json={"data": {"categoryCreate": {
        "category": {"id": saleor_id, "slug": slug, "name": "Платья"},
        "errors": [],
    }}})


@respx.mock
@pytest.mark.asyncio
async def test_create_category_retries_on_slug_conflict():
    route = respx.post(_URL).mock(side_effect=[_slug_conflict(), _created("Q2F0OjE=", "platya-9")])
    client = SaleorClient(api_url=_URL, app_token="t")

    cid = await create_category(
        client, name="Платья", slug="platya", parent_saleor_id=None, suffix_seed="9"
    )
    assert cid == "Q2F0OjE="
    assert route.call_count == 2

    # the second call went out with the suffix that resolves the collision
    second_body = json.loads(route.calls[1].request.content)
    assert second_body["variables"]["input"]["slug"] == "platya-9"


@respx.mock
@pytest.mark.asyncio
async def test_create_category_first_try_ok():
    route = respx.post(_URL).mock(return_value=_created("Q2F0OjI=", "obuv"))
    client = SaleorClient(api_url=_URL, app_token="t")
    cid = await create_category(
        client, name="Обувь", slug="obuv", parent_saleor_id=None, suffix_seed="3"
    )
    assert cid == "Q2F0OjI="
    assert route.call_count == 1
