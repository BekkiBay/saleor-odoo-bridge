"""Customer domain model."""

from __future__ import annotations

from pydantic import BaseModel

from saleor_bridge.domain.address import Address


class Customer(BaseModel):
    external_id: str            # Saleor User.id (base64, stored as-is)
    # Plain str, not EmailStr: phone-login shoppers carry a synthetic identity
    # email ("998…@phone.example.local"); ".local" is a reserved TLD that
    # email-validator rejects. Saleor already validated it; Odoo email is free-text.
    email: str
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    default_billing_address: Address | None = None
    default_shipping_address: Address | None = None
    metadata: dict[str, str] = {}

    @property
    def display_name(self) -> str:
        name = f"{self.first_name or ''} {self.last_name or ''}".strip()
        return name or str(self.email)
