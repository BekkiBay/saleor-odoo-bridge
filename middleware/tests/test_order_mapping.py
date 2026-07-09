"""Saleor payload → domain.Order mapping tests."""

from __future__ import annotations

from decimal import Decimal

from saleor_bridge.adapters.saleor.order_mapper import extract_order, saleor_order_to_order
from saleor_bridge.domain.enums import OrderStatus


ORDER_PAYLOAD = {
    "event": {
        "order": {
            "id": "T3JkZXI6MQ==",
            "number": "1042",
            "created": "2026-05-21T10:30:00+00:00",
            "user": {"id": "VXNlcjox", "email": "alice@example.com",
                     "firstName": "Alice", "lastName": "Smith"},
            "userEmail": "alice@example.com",
            "billingAddress": {
                "firstName": "Alice", "lastName": "Smith",
                "streetAddress1": "Amir Temur 1", "city": "Tashkent",
                "country": {"code": "UZ"}, "phone": "+998901234567",
            },
            "shippingAddress": {
                "firstName": "Alice", "lastName": "Smith",
                "streetAddress1": "Chilanzar 5", "city": "Tashkent",
                "country": {"code": "UZ"},
            },
            "lines": [
                {"productName": "Платье", "variantName": "M", "productSku": "SKU-001",
                 "quantity": 2, "unitPrice": {"gross": {"amount": "450000", "currency": "UZS"}},
                 "variant": {"id": "x", "sku": "SKU-001"}},
            ],
            "total": {"gross": {"amount": "900000", "currency": "UZS"}},
            "status": "UNFULFILLED",
            "paymentStatus": "FULLY_CHARGED",
        }
    }
}


def test_order_map_draft():
    so = extract_order(ORDER_PAYLOAD)
    order = saleor_order_to_order(so, status=OrderStatus.DRAFT)
    assert order.external_id == "T3JkZXI6MQ=="
    assert order.external_number == "1042"
    assert order.client_order_ref == "saleor-1042"
    assert order.customer_email == "alice@example.com"
    assert order.customer_external_id == "VXNlcjox"
    assert order.status == OrderStatus.DRAFT
    assert order.total == Decimal("900000")
    assert order.currency == "UZS"
    assert len(order.lines) == 1
    line = order.lines[0]
    assert line.sku == "SKU-001"
    assert line.quantity == 2
    assert line.unit_price == Decimal("450000")
    assert order.created_at is not None
    assert order.created_at.tzinfo is None  # naive UTC


def test_order_status_from_event():
    so = extract_order(ORDER_PAYLOAD)
    assert saleor_order_to_order(so, status=OrderStatus.CONFIRMED).status == OrderStatus.CONFIRMED
    assert saleor_order_to_order(so, status=OrderStatus.CANCELLED).status == OrderStatus.CANCELLED


def test_guest_order_no_user():
    payload = {"event": {"order": {
        "id": "T3JkZXI6Mg==", "number": "1043",
        "userEmail": "guest@example.com",
        "lines": [], "total": {"gross": {"amount": "0", "currency": "UZS"}},
    }}}
    so = extract_order(payload)
    order = saleor_order_to_order(so, status=OrderStatus.DRAFT)
    assert order.customer_email == "guest@example.com"
    assert order.customer_external_id is None


def test_order_map_explicit_null_optional_strings():
    """Saleor sends explicit null (not absent) for empty optional strings —
    voucherCode/shippingMethodName for orders without a promo/method, and
    optional address fields. These must coerce to "" instead of raising
    ValidationError (regression: string_type on voucherCode=None dropped the
    whole ORDER_CREATED sync)."""
    payload = {"event": {"order": {
        "id": "T3JkZXI6OTk=", "number": "1099",
        "userEmail": "no-promo@example.com",
        "billingAddress": {
            "firstName": "Bob", "lastName": "Lee",
            "companyName": None, "streetAddress1": "Yunusabad 3",
            "streetAddress2": None, "city": "Tashkent",
            "postalCode": None, "country": {"code": "UZ"}, "phone": None,
        },
        "lines": [],
        "shippingMethodName": None,
        "voucherCode": None,
        "total": {"gross": {"amount": "0", "currency": "UZS"}},
    }}}
    so = extract_order(payload)  # must not raise
    assert so.voucherCode == ""
    assert so.shippingMethodName == ""
    assert so.billingAddress is not None
    assert so.billingAddress.phone == ""
    assert so.billingAddress.streetAddress2 == ""


def test_order_map_synthetic_phone_email():
    """Phone-login shoppers carry a synthetic "<phone>@phone.justix.local" email.
    ".local" is a reserved TLD that EmailStr rejects — the domain Order must accept
    it (plain str) so the order still syncs to Odoo (regression: whole sync dropped)."""
    payload = {"event": {"order": {
        "id": "T3JkZXI6MTAx", "number": "1101",
        "userEmail": "998901112233@phone.justix.local",
        "lines": [],
        "total": {"gross": {"amount": "0", "currency": "UZS"}},
    }}}
    so = extract_order(payload)
    order = saleor_order_to_order(so, status=OrderStatus.DRAFT)  # must not raise
    assert order.customer_email == "998901112233@phone.justix.local"


def test_sku_fallback_to_variant():
    payload = {"event": {"order": {
        "id": "T3JkZXI6Mw==", "number": "1044", "userEmail": "g@e.com",
        "lines": [{"productName": "X", "quantity": 1,
                   "unitPrice": {"gross": {"amount": "1", "currency": "UZS"}},
                   "variant": {"id": "v", "sku": "SKU-FALLBACK"}}],
        "total": {"gross": {"amount": "1", "currency": "UZS"}},
    }}}
    so = extract_order(payload)
    order = saleor_order_to_order(so, status=OrderStatus.DRAFT)
    assert order.lines[0].sku == "SKU-FALLBACK"
