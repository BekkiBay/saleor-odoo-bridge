"""Idempotency: pre-check status → skip the mutation if already in the target state."""

from __future__ import annotations

import pytest
import respx

from saleor_bridge.adapters.saleor import order_mutations as om
from saleor_bridge.saleor.client import SaleorClient
from tests.saleor_order_fakes import make_saleor_router, order_node

_URL = "http://saleor.test/graphql/"
_OID = "T3JkZXI6MQ=="


def _client() -> SaleorClient:
    return SaleorClient(api_url=_URL, app_token="t")


@respx.mock
@pytest.mark.asyncio
async def test_confirm_skips_when_not_unconfirmed():
    cap: list = []
    respx.post(_URL).mock(side_effect=make_saleor_router(order_node(status="UNFULFILLED"), capture=cap))
    res = await om.confirm_order(_client(), _OID)
    assert res.ok and "skipped" in res.message
    assert not any("orderConfirm(" in b["query"] for b in cap)


@respx.mock
@pytest.mark.asyncio
async def test_confirm_runs_when_unconfirmed():
    cap: list = []
    respx.post(_URL).mock(side_effect=make_saleor_router(order_node(status="UNCONFIRMED"), capture=cap))
    res = await om.confirm_order(_client(), _OID)
    assert res.ok
    assert any("orderConfirm(" in b["query"] for b in cap)


@respx.mock
@pytest.mark.asyncio
async def test_cancel_skips_when_already_canceled():
    cap: list = []
    respx.post(_URL).mock(side_effect=make_saleor_router(order_node(status="CANCELED"), capture=cap))
    res = await om.cancel_order(_client(), _OID)
    assert res.ok
    assert not any("orderCancel(" in b["query"] for b in cap)


@respx.mock
@pytest.mark.asyncio
async def test_cancel_refused_after_fulfilled():
    cap: list = []
    respx.post(_URL).mock(side_effect=make_saleor_router(order_node(status="FULFILLED"), capture=cap))
    res = await om.cancel_order(_client(), _OID)
    assert not res.ok and "return flow" in res.message
    assert not any("orderCancel(" in b["query"] for b in cap)


@respx.mock
@pytest.mark.asyncio
async def test_mark_paid_skips_when_already_paid():
    cap: list = []
    respx.post(_URL).mock(side_effect=make_saleor_router(order_node(is_paid=True), capture=cap))
    res = await om.mark_paid(_client(), _OID)
    assert res.ok
    assert not any("orderMarkAsPaid(" in b["query"] for b in cap)
