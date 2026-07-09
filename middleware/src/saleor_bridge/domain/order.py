"""Order domain model."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from saleor_bridge.domain.address import Address
from saleor_bridge.domain.enums import OrderStatus


class OrderLine(BaseModel):
    sku: str                 # natural key для product lookup (ADR-0007)
    product_name: str        # для логов / fallback name
    quantity: int
    unit_price: Decimal
    currency: str            # ISO 4217
    net_unit_price: Decimal = Decimal("0")
    tax_amount: Decimal = Decimal("0")
    tax_rate: Decimal = Decimal("0")          # percent, e.g. 12
    undiscounted_unit_price: Decimal = Decimal("0")
    discount_amount: Decimal = Decimal("0")


class Order(BaseModel):
    external_id: str              # Saleor Order.id
    external_number: str          # Saleor Order.number (human-readable)
    # Plain str, not EmailStr: phone-login shoppers carry a synthetic identity
    # email (e.g. "998…@phone.justix.local"). ".local" is a reserved TLD that
    # email-validator rejects, which would drop the whole order sync. Saleor has
    # already validated the address on registration; Odoo's partner.email is a
    # free-text field, so strict re-validation here only causes false rejects.
    customer_email: str
    customer_external_id: str | None = None  # User.id if logged in
    lines: list[OrderLine] = []
    billing_address: Address | None = None
    shipping_address: Address | None = None
    total: Decimal = Decimal("0")
    currency: str = "UZS"
    status: OrderStatus = OrderStatus.DRAFT
    created_at: datetime | None = None
    metadata: dict[str, str] = {}
    shipping_net: Decimal = Decimal("0")
    shipping_tax: Decimal = Decimal("0")
    shipping_tax_rate: Decimal = Decimal("0")  # percent
    shipping_method_name: str = ""
    discounts: list[str] = []                  # human summaries for the order note
    voucher_code: str = ""
    total_net: Decimal = Decimal("0")
    total_tax: Decimal = Decimal("0")

    @property
    def client_order_ref(self) -> str:
        """Idempotency key для sale.order (ADR-0005/0007)."""
        return f"saleor-{self.external_number}"
