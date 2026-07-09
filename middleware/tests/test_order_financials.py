"""P0 order financials: payload parse → domain → Odoo build."""
from __future__ import annotations

from decimal import Decimal

import pytest

from saleor_bridge.adapters.odoo import product as product_adapter
from saleor_bridge.adapters.odoo import sale_order as so_adapter
from saleor_bridge.adapters.odoo import tax as tax_adapter
from saleor_bridge.adapters.odoo.binding import BindingRepository
from saleor_bridge.adapters.saleor.order_mapper import saleor_order_to_order
from saleor_bridge.adapters.saleor.payload_models import SaleorOrder
from saleor_bridge.domain.enums import OrderStatus
from saleor_bridge.domain.order import Order, OrderLine
from saleor_bridge.usecases.sync_order import _check_total_guard
from tests.stock_fakes import FakeOdoo


@pytest.fixture(autouse=True)
def _clear_tax_cache():
    """Isolate module-level tax and product caches between tests."""
    tax_adapter._cache.clear()
    product_adapter._cache.clear()
    yield
    tax_adapter._cache.clear()
    product_adapter._cache.clear()


RICH_PAYLOAD = {
    "id": "T3JkZXI6OQ==", "number": "2001", "userEmail": "p0@example.com",
    "lines": [{
        "productName": "Jacket", "variantName": "L", "productSku": "SKU-9",
        "quantity": 2,
        "unitPrice": {"net": {"amount": "100000"}, "gross": {"amount": "112000"}, "tax": {"amount": "12000"}},
        "undiscountedUnitPrice": {"gross": {"amount": "130000"}},
        "unitDiscount": {"amount": "18000"},
        "totalPrice": {"net": {"amount": "200000"}, "gross": {"amount": "224000"}, "tax": {"amount": "24000"}},
        "taxRate": "0.12",
        "variant": {"id": "v9", "sku": "SKU-9"},
    }],
    "shippingPrice": {"net": {"amount": "20000"}, "gross": {"amount": "22400"}, "tax": {"amount": "2400"}},
    "shippingMethodName": "Courier",
    "discounts": [{"valueType": "FIXED", "value": "36000", "amount": {"amount": "36000"}, "reason": "PROMO10"}],
    "voucherCode": "PROMO10",
    "total": {"net": {"amount": "220000"}, "gross": {"amount": "246400"}, "tax": {"amount": "26400"}},
    "status": "UNFULFILLED", "paymentStatus": "FULLY_CHARGED",
}


def test_payload_parses_financials():
    so = SaleorOrder.model_validate(RICH_PAYLOAD)
    line = so.lines[0]
    assert line.unitPrice.net.amount == Decimal("100000")
    assert line.unitPrice.tax.amount == Decimal("12000")
    assert line.undiscountedUnitPrice.gross.amount == Decimal("130000")
    assert line.unitDiscount.amount == Decimal("18000")
    assert line.taxRate == Decimal("0.12")
    assert so.shippingPrice.net.amount == Decimal("20000")
    assert so.shippingPrice.tax.amount == Decimal("2400")
    assert so.shippingMethodName == "Courier"
    assert so.voucherCode == "PROMO10"
    assert so.discounts[0].amount.amount == Decimal("36000")
    assert so.total.net.amount == Decimal("220000")
    assert so.total.tax.amount == Decimal("26400")


def test_payload_backward_compatible_without_financials():
    """Old gross-only payload still parses (new fields default)."""
    so = SaleorOrder.model_validate({
        "id": "T3JkZXI6MQ==", "number": "1", "userEmail": "a@b.co",
        "lines": [{"productSku": "S1", "quantity": 1,
                   "unitPrice": {"gross": {"amount": "5000"}}, "variant": {"sku": "S1"}}],
        "total": {"gross": {"amount": "5000"}}, "status": "UNFULFILLED", "paymentStatus": "NOT_CHARGED",
    })
    assert so.lines[0].unitPrice.net.amount == Decimal("0")
    assert so.shippingPrice.net.amount == Decimal("0")
    assert so.lines[0].taxRate == Decimal("0")
    assert so.voucherCode == ""


def test_mapper_populates_financials():
    so = SaleorOrder.model_validate(RICH_PAYLOAD)
    order = saleor_order_to_order(so, status=OrderStatus.DRAFT)
    line = order.lines[0]
    assert line.net_unit_price == Decimal("100000")
    assert line.tax_amount == Decimal("12000")
    assert line.tax_rate == Decimal("12")           # percent, 0.12 * 100
    assert line.undiscounted_unit_price == Decimal("130000")
    assert line.discount_amount == Decimal("18000")
    assert order.shipping_net == Decimal("20000")
    assert order.shipping_tax == Decimal("2400")
    assert order.shipping_tax_rate == Decimal("12")  # 2400/20000*100
    assert order.shipping_method_name == "Courier"
    assert order.voucher_code == "PROMO10"
    assert order.total_net == Decimal("220000")
    assert order.total_tax == Decimal("26400")
    assert any("PROMO10" in d for d in order.discounts)


def test_mapper_old_payload_net_falls_back_to_gross():
    so = SaleorOrder.model_validate({
        "id": "T3JkZXI6MQ==", "number": "1", "userEmail": "a@b.co",
        "lines": [{"productSku": "S1", "quantity": 1,
                   "unitPrice": {"gross": {"amount": "5000"}}, "variant": {"sku": "S1"}}],
        "total": {"gross": {"amount": "5000"}}, "status": "UNFULFILLED", "paymentStatus": "NOT_CHARGED",
    })
    order = saleor_order_to_order(so, status=OrderStatus.DRAFT)
    assert order.lines[0].net_unit_price == Decimal("5000")  # net 0 → fall back to gross
    assert order.lines[0].tax_rate == Decimal("0")
    assert order.shipping_net == Decimal("0")


@pytest.mark.asyncio
async def test_resolve_sale_tax_finds_account_tax():
    odoo = FakeOdoo(taxes={12.0: 7})
    assert await tax_adapter.resolve_sale_tax(odoo, Decimal("12")) == 7


@pytest.mark.asyncio
async def test_resolve_sale_tax_missing_raises():
    odoo = FakeOdoo(taxes={})
    with pytest.raises(tax_adapter.TaxNotConfigured):
        await tax_adapter.resolve_sale_tax(odoo, Decimal("12"))


@pytest.mark.asyncio
async def test_build_lines_uses_net_price_and_tax_id():
    odoo = FakeOdoo(products={"SKU-9": 55}, taxes={12.0: 7})
    order = Order(
        external_id="o", external_number="9", customer_email="a@b.co",
        lines=[OrderLine(sku="SKU-9", product_name="Jacket", quantity=2,
                         unit_price=Decimal("112000"), currency="UZS",
                         net_unit_price=Decimal("100000"), tax_amount=Decimal("12000"),
                         tax_rate=Decimal("12"))],
    )
    cmds = await so_adapter.build_order_lines(odoo, order)
    vals = cmds[0][2]
    assert vals["price_unit"] == 100000.0       # net, not gross
    assert vals["tax_ids"] == [(6, 0, [7])]


@pytest.mark.asyncio
async def test_build_lines_no_tax_when_rate_zero():
    odoo = FakeOdoo(products={"S1": 55})
    order = Order(external_id="o", external_number="1", customer_email="a@b.co",
                  lines=[OrderLine(sku="S1", product_name="X", quantity=1,
                                   unit_price=Decimal("5000"), currency="UZS",
                                   net_unit_price=Decimal("5000"), tax_rate=Decimal("0"))])
    cmds = await so_adapter.build_order_lines(odoo, order)
    assert "tax_ids" not in cmds[0][2]
    assert cmds[0][2]["price_unit"] == 5000.0


@pytest.mark.asyncio
async def test_resolve_shipping_product_missing_raises():
    odoo = FakeOdoo(products={})
    with pytest.raises(product_adapter.ShippingProductNotConfigured):
        await product_adapter.resolve_shipping_product(odoo, "SHIPPING")


@pytest.mark.asyncio
async def test_create_draft_adds_shipping_line():
    odoo = FakeOdoo(products={"SKU-9": 55, "SHIPPING": 99}, taxes={12.0: 7})
    order = Order(
        external_id="o", external_number="9", customer_email="a@b.co",
        lines=[OrderLine(sku="SKU-9", product_name="Jacket", quantity=2,
                         unit_price=Decimal("112000"), currency="UZS",
                         net_unit_price=Decimal("100000"), tax_rate=Decimal("12"))],
        shipping_net=Decimal("20000"), shipping_tax=Decimal("2400"),
        shipping_tax_rate=Decimal("12"), shipping_method_name="Courier",
    )
    await so_adapter.create_draft_order(odoo, order, partner_id=1, invoice_id=1, shipping_id=1,
                                        shipping_sku="SHIPPING")
    create = next(c for c in odoo.calls if c[1] == "create")
    order_lines = create[2]["vals_list"][0]["order_line"]
    ship = [ln for ln in order_lines if ln[2]["product_id"] == 99]
    assert len(ship) == 1
    assert ship[0][2]["price_unit"] == 20000.0
    assert ship[0][2]["tax_ids"] == [(6, 0, [7])]


@pytest.mark.asyncio
async def test_create_draft_no_shipping_line_when_zero():
    odoo = FakeOdoo(products={"SKU-9": 55}, taxes={12.0: 7})
    order = Order(external_id="o", external_number="9", customer_email="a@b.co",
                  lines=[OrderLine(sku="SKU-9", product_name="K", quantity=1,
                                   unit_price=Decimal("112000"), currency="UZS",
                                   net_unit_price=Decimal("100000"), tax_rate=Decimal("12"))])
    await so_adapter.create_draft_order(odoo, order, partner_id=1, invoice_id=1, shipping_id=1,
                                        shipping_sku="SHIPPING")
    create = next(c for c in odoo.calls if c[1] == "create")
    order_lines = create[2]["vals_list"][0]["order_line"]
    assert all(ln[2]["product_id"] != 99 for ln in order_lines)


@pytest.mark.asyncio
async def test_create_draft_writes_discount_note():
    odoo = FakeOdoo(products={"SKU-9": 55}, taxes={12.0: 7})
    order = Order(external_id="o", external_number="9", customer_email="a@b.co",
                  lines=[OrderLine(sku="SKU-9", product_name="K", quantity=1,
                                   unit_price=Decimal("112000"), currency="UZS",
                                   net_unit_price=Decimal("100000"), tax_rate=Decimal("12"))],
                  discounts=["PROMO10: -36000"], voucher_code="PROMO10")
    await so_adapter.create_draft_order(odoo, order, partner_id=1, invoice_id=1, shipping_id=1)
    create = next(c for c in odoo.calls if c[1] == "create")
    note = create[2]["vals_list"][0].get("note", "")
    assert "PROMO10" in note


@pytest.mark.asyncio
async def test_build_lines_raises_on_unmappable_sku():
    odoo = FakeOdoo(products={})   # SKU-9 not in Odoo
    order = Order(external_id="o", external_number="9", customer_email="a@b.co",
                  lines=[OrderLine(sku="SKU-9", product_name="K", quantity=1,
                                   unit_price=Decimal("1"), currency="UZS",
                                   net_unit_price=Decimal("1"))])
    with pytest.raises(so_adapter.UnmappableSku):
        await so_adapter.build_order_lines(odoo, order)


def test_order_totals_match_pure():
    assert so_adapter.order_totals_match(Decimal("246400"), Decimal("246400"), 1) is True
    assert so_adapter.order_totals_match(Decimal("246401"), Decimal("246400"), 1) is True   # within tol
    assert so_adapter.order_totals_match(Decimal("246410"), Decimal("246400"), 1) is False  # beyond tol


@pytest.mark.asyncio
async def test_check_total_guard_passes_when_match():
    odoo = FakeOdoo(sale_orders={1: {"state": "draft", "name": "S1", "amount_total": 112000}})
    order = Order(external_id="o", external_number="9", customer_email="a@b.co",
                  total=Decimal("112000"))
    warnings: list = []
    ok = await _check_total_guard(order, odoo, BindingRepository(odoo), 1, warnings)
    assert ok is True
    assert warnings == []


@pytest.mark.asyncio
async def test_check_total_guard_marks_diverged_on_mismatch():
    odoo = FakeOdoo(sale_orders={1: {"state": "draft", "name": "S1", "amount_total": 999999}})
    order = Order(external_id="o", external_number="9", customer_email="a@b.co",
                  total=Decimal("112000"))
    warnings: list = []
    ok = await _check_total_guard(order, odoo, BindingRepository(odoo), 1, warnings)
    assert ok is False
    assert any("total mismatch" in w for w in warnings)
    assert any(m == "saleor.binding" and vals.get("sync_state") == "diverged"
               for m, vals in odoo.creates)
