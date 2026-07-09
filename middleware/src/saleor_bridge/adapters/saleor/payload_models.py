"""Raw Saleor webhook payload models (pydantic).

These models mirror the shape of the subscription queries in manifest.py. They are
Saleor-specific and must not leak into domain/ or usecases/.

Saleor payloads arrive either as {"event": {...}} with subscription queries, OR as
a direct object in legacy webhooks. We support both: parse whatever came in.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, Field


def _none_to_empty(v: object) -> object:
    """Saleor sends explicit null (not an absent key) for empty optional strings,
    e.g. voucherCode / shippingMethodName / optional address fields on orders with
    no promo/method. A plain `str = ""` default only covers an *absent* key, so a
    literal null raises string_type and drops the whole sync. Coerce null → ""."""
    return "" if v is None else v


# String field that tolerates an explicit JSON null from Saleor (→ "").
NullableStr = Annotated[str, BeforeValidator(_none_to_empty)]


class SaleorCountry(BaseModel):
    code: NullableStr = ""


class SaleorAddress(BaseModel):
    firstName: NullableStr = ""
    lastName: NullableStr = ""
    companyName: NullableStr = ""
    streetAddress1: NullableStr = ""
    streetAddress2: NullableStr = ""
    city: NullableStr = ""
    postalCode: NullableStr = ""
    country: SaleorCountry = Field(default_factory=SaleorCountry)
    phone: NullableStr = ""


class SaleorUser(BaseModel):
    id: str
    email: str
    firstName: NullableStr = ""
    lastName: NullableStr = ""
    defaultBillingAddress: SaleorAddress | None = None
    defaultShippingAddress: SaleorAddress | None = None


class SaleorMoney(BaseModel):
    amount: Decimal = Decimal("0")
    currency: str = ""


class SaleorTaxedMoney(BaseModel):
    net: SaleorMoney = Field(default_factory=SaleorMoney)
    gross: SaleorMoney = Field(default_factory=SaleorMoney)
    tax: SaleorMoney = Field(default_factory=SaleorMoney)


class SaleorVariant(BaseModel):
    id: NullableStr = ""
    sku: NullableStr = ""


class SaleorOrderDiscount(BaseModel):
    valueType: NullableStr = ""
    value: Decimal = Decimal("0")
    amount: SaleorMoney = Field(default_factory=SaleorMoney)
    reason: NullableStr = ""


class SaleorOrderLine(BaseModel):
    id: NullableStr = ""
    productName: NullableStr = ""
    variantName: NullableStr = ""
    productSku: NullableStr = ""
    quantity: int = 0
    unitPrice: SaleorTaxedMoney = Field(default_factory=SaleorTaxedMoney)
    undiscountedUnitPrice: SaleorTaxedMoney = Field(default_factory=SaleorTaxedMoney)
    unitDiscount: SaleorMoney = Field(default_factory=SaleorMoney)
    totalPrice: SaleorTaxedMoney = Field(default_factory=SaleorTaxedMoney)
    taxRate: Decimal = Decimal("0")
    variant: SaleorVariant | None = None

    @property
    def resolved_sku(self) -> str:
        """productSku primary; variant.sku fallback."""
        return self.productSku or (self.variant.sku if self.variant else "")


class SaleorOrder(BaseModel):
    id: str
    number: NullableStr = ""
    created: str | None = None
    user: SaleorUser | None = None
    userEmail: NullableStr = ""
    billingAddress: SaleorAddress | None = None
    shippingAddress: SaleorAddress | None = None
    lines: list[SaleorOrderLine] = []
    shippingPrice: SaleorTaxedMoney = Field(default_factory=SaleorTaxedMoney)
    shippingMethodName: NullableStr = ""
    discounts: list[SaleorOrderDiscount] = []
    voucherCode: NullableStr = ""
    total: SaleorTaxedMoney = Field(default_factory=SaleorTaxedMoney)
    status: NullableStr = ""
    paymentStatus: NullableStr = ""
