"""SaleorOrder payload → domain.Order."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from saleor_bridge.adapters.saleor.payload_models import SaleorAddress, SaleorOrder
from saleor_bridge.domain.address import Address
from saleor_bridge.domain.enums import OrderStatus
from saleor_bridge.domain.order import Order, OrderLine


def _rate_pct(net: Decimal, tax: Decimal) -> Decimal:
    """Derive a tax rate (percent) from net+tax amounts; 0 when net is 0."""
    if net <= 0:
        return Decimal("0")
    return (tax / net * 100).quantize(Decimal("0.01"))


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


def extract_order(payload: dict[str, Any]) -> SaleorOrder:
    """Extract the order from the webhook payload (subscription or legacy)."""
    data = payload
    if "event" in payload and isinstance(payload["event"], dict):
        data = payload["event"]
    if "order" in data and isinstance(data["order"], dict):
        data = data["order"]
    return SaleorOrder.model_validate(data)


def _parse_created(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        # Saleor returns ISO-8601 with Z. Normalize to naive UTC.
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def saleor_order_to_order(so: SaleorOrder, *, status: OrderStatus) -> Order:
    email = so.userEmail or (so.user.email if so.user else "")
    cust_id = so.user.id if so.user else None

    lines = [
        OrderLine(
            sku=line.resolved_sku,
            product_name=f"{line.productName} {line.variantName}".strip(),
            quantity=line.quantity,
            unit_price=line.unitPrice.gross.amount,
            currency=line.unitPrice.gross.currency or so.total.gross.currency,
            net_unit_price=(line.unitPrice.net.amount or line.unitPrice.gross.amount),
            tax_amount=line.unitPrice.tax.amount,
            tax_rate=(line.taxRate * 100).quantize(Decimal("0.01")),
            undiscounted_unit_price=line.undiscountedUnitPrice.gross.amount,
            discount_amount=line.unitDiscount.amount,
        )
        for line in so.lines
    ]
    discounts = [
        f"{d.reason or d.valueType}: -{d.amount.amount}".strip()
        for d in so.discounts
    ]

    return Order(
        external_id=so.id,
        external_number=so.number or so.id,
        customer_email=email,
        customer_external_id=cust_id,
        lines=lines,
        billing_address=_addr_to_domain(so.billingAddress, billing=True, shipping=False),
        shipping_address=_addr_to_domain(so.shippingAddress, billing=False, shipping=True),
        total=so.total.gross.amount,
        currency=so.total.gross.currency or "",
        status=status,
        created_at=_parse_created(so.created),
        shipping_net=so.shippingPrice.net.amount,
        shipping_tax=so.shippingPrice.tax.amount,
        shipping_tax_rate=_rate_pct(so.shippingPrice.net.amount, so.shippingPrice.tax.amount),
        shipping_method_name=so.shippingMethodName,
        discounts=discounts,
        voucher_code=so.voucherCode,
        total_net=so.total.net.amount,
        total_tax=so.total.tax.amount,
    )
