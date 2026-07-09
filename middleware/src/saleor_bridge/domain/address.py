"""Address domain model."""

from __future__ import annotations

from pydantic import BaseModel


class Address(BaseModel):
    first_name: str = ""
    last_name: str = ""
    company_name: str | None = None
    street_address_1: str = ""
    street_address_2: str | None = None
    city: str = ""
    postal_code: str | None = None
    country_code: str = ""  # ISO 3166-1 alpha-2
    phone: str | None = None
    is_billing: bool = False
    is_shipping: bool = False

    @property
    def full_name(self) -> str:
        name = f"{self.first_name} {self.last_name}".strip()
        return name or self.company_name or "Address"
