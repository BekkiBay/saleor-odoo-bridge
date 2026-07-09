"""SaleorUser payload → domain.Customer."""

from __future__ import annotations

from typing import Any

from saleor_bridge.adapters.saleor.payload_models import SaleorAddress, SaleorUser
from saleor_bridge.domain.address import Address
from saleor_bridge.domain.customer import Customer


def _addr_to_domain(a: SaleorAddress | None, *, billing: bool, shipping: bool) -> Address | None:
    if a is None:
        return None
    return Address(
        first_name=a.firstName,
        last_name=a.lastName,
        company_name=a.companyName or None,
        street_address_1=a.streetAddress1,
        street_address_2=a.streetAddress2 or None,
        city=a.city,
        postal_code=a.postalCode or None,
        country_code=a.country.code,
        phone=a.phone or None,
        is_billing=billing,
        is_shipping=shipping,
    )


def extract_user(payload: dict[str, Any]) -> SaleorUser:
    """Достать user-объект из webhook payload.

    Subscription payload: {"event": {"user": {...}}}.
    Legacy payload: прямой user объект {...}.
    """
    data = payload
    if "event" in payload and isinstance(payload["event"], dict):
        data = payload["event"]
    if "user" in data and isinstance(data["user"], dict):
        data = data["user"]
    return SaleorUser.model_validate(data)


def saleor_user_to_customer(user: SaleorUser) -> Customer:
    phone = ""
    if user.defaultBillingAddress:
        phone = user.defaultBillingAddress.phone
    elif user.defaultShippingAddress:
        phone = user.defaultShippingAddress.phone

    return Customer(
        external_id=user.id,
        email=user.email,
        first_name=user.firstName or None,
        last_name=user.lastName or None,
        phone=phone or None,
        default_billing_address=_addr_to_domain(
            user.defaultBillingAddress, billing=True, shipping=False
        ),
        default_shipping_address=_addr_to_domain(
            user.defaultShippingAddress, billing=False, shipping=True
        ),
    )
