"""Saleor payload → domain.Customer mapping tests."""

from __future__ import annotations

from saleor_bridge.adapters.saleor.customer_mapper import (
    extract_user,
    saleor_user_to_customer,
)


SUBSCRIPTION_PAYLOAD = {
    "event": {
        "user": {
            "id": "VXNlcjox",
            "email": "alice@example.com",
            "firstName": "Alice",
            "lastName": "Smith",
            "defaultBillingAddress": {
                "firstName": "Alice",
                "lastName": "Smith",
                "streetAddress1": "Amir Temur 1",
                "city": "Tashkent",
                "postalCode": "100000",
                "country": {"code": "UZ"},
                "phone": "+998901234567",
            },
            "defaultShippingAddress": {
                "firstName": "Alice",
                "lastName": "Smith",
                "streetAddress1": "Chilanzar 5",
                "city": "Tashkent",
                "country": {"code": "UZ"},
                "phone": "+998901234567",
            },
        }
    }
}


def test_extract_and_map():
    user = extract_user(SUBSCRIPTION_PAYLOAD)
    c = saleor_user_to_customer(user)
    assert c.external_id == "VXNlcjox"
    assert c.email == "alice@example.com"
    assert c.display_name == "Alice Smith"
    assert c.phone == "+998901234567"
    assert c.default_billing_address.is_billing
    assert c.default_billing_address.country_code == "UZ"
    assert c.default_shipping_address.is_shipping


def test_display_name_falls_back_to_email():
    user = extract_user({"event": {"user": {"id": "VXNlcjoy", "email": "x@y.com"}}})
    c = saleor_user_to_customer(user)
    assert c.display_name == "x@y.com"


def test_legacy_direct_user_payload():
    """Не-subscription payload (прямой user объект)."""
    user = extract_user({"id": "VXNlcjoz", "email": "bob@example.com", "firstName": "Bob"})
    c = saleor_user_to_customer(user)
    assert c.external_id == "VXNlcjoz"
    assert c.first_name == "Bob"
