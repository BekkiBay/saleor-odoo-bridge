"""billing/shipping → child contacts mapping tests."""

from __future__ import annotations

from saleor_bridge.domain.address import Address


def test_billing_shipping_flags():
    billing = Address(first_name="A", last_name="B", street_address_1="S1",
                      city="Tashkent", country_code="UZ", is_billing=True)
    shipping = Address(first_name="A", last_name="B", street_address_1="S2",
                       city="Tashkent", country_code="UZ", is_shipping=True)
    assert billing.is_billing and not billing.is_shipping
    assert shipping.is_shipping and not shipping.is_billing


def test_full_name_fallbacks():
    assert Address(first_name="A", last_name="B").full_name == "A B"
    assert Address(company_name="Acme").full_name == "Acme"
    assert Address().full_name == "Address"


def test_customer_addresses_map_to_types():
    """Customer.default_billing → invoice; default_shipping → delivery."""
    from saleor_bridge.domain.customer import Customer

    c = Customer(
        external_id="VXNlcjox", email="a@b.com",
        default_billing_address=Address(street_address_1="bill", country_code="UZ", is_billing=True),
        default_shipping_address=Address(street_address_1="ship", country_code="UZ", is_shipping=True),
    )
    assert c.default_billing_address.is_billing
    assert c.default_shipping_address.is_shipping
