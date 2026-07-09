"""Pydantic-схема Saleor App Manifest.

Reference: https://docs.saleor.io/developer/extending/apps/architecture/manifest
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class WebhookManifest(BaseModel):
    name: str
    targetUrl: str
    query: str
    asyncEvents: list[str] = []
    syncEvents: list[str] = []
    isActive: bool = True


class AppManifest(BaseModel):
    """Минимальный набор полей."""

    id: str = "uz.justix.saleor-bridge"
    version: str = "0.3.0"
    name: str = "Justix Odoo Sync"
    about: str = "Bidirectional sync between Justix Odoo back-office and Saleor storefront."

    permissions: list[str] = Field(
        default_factory=lambda: [
            "MANAGE_ORDERS",
            "MANAGE_PRODUCTS",
            "MANAGE_USERS",
            "MANAGE_PRODUCT_TYPES_AND_ATTRIBUTES",
            "MANAGE_CHANNELS",
        ]
    )

    appUrl: str
    tokenTargetUrl: str
    dataPrivacyUrl: str
    homepageUrl: str = "https://justix.uz"
    supportUrl: str = "mailto:support@justix.uz"

    extensions: list[dict] = []
    webhooks: list[WebhookManifest] = []

    requiredSaleorVersion: str = "^3.20"
    author: str = "Justix Market"

    @classmethod
    def build(cls, public_url: str) -> AppManifest:
        """Manifest с substituted public URL + все 6 Phase 3.1 webhooks."""
        base = public_url.rstrip("/")
        wh = f"{base}/api/webhooks"
        return cls(
            appUrl=base,
            tokenTargetUrl=f"{base}/api/register",
            dataPrivacyUrl=f"{base}/legal/privacy",
            webhooks=[
                WebhookManifest(
                    name="Customer created",
                    asyncEvents=["CUSTOMER_CREATED"],
                    query=_CUSTOMER_SUBSCRIPTION,
                    targetUrl=f"{wh}/customer-created",
                ),
                WebhookManifest(
                    name="Customer updated",
                    asyncEvents=["CUSTOMER_UPDATED"],
                    query=_CUSTOMER_SUBSCRIPTION,
                    targetUrl=f"{wh}/customer-updated",
                ),
                WebhookManifest(
                    name="Order created",
                    asyncEvents=["ORDER_CREATED"],
                    query=_ORDER_SUBSCRIPTION,
                    targetUrl=f"{wh}/order-created",
                ),
                WebhookManifest(
                    name="Order confirmed",
                    asyncEvents=["ORDER_CONFIRMED"],
                    query=_ORDER_SUBSCRIPTION,
                    targetUrl=f"{wh}/order-confirmed",
                ),
                WebhookManifest(
                    name="Order fully paid",
                    asyncEvents=["ORDER_FULLY_PAID"],
                    query=_ORDER_SUBSCRIPTION,
                    targetUrl=f"{wh}/order-fully-paid",
                ),
                WebhookManifest(
                    name="Order cancelled",
                    asyncEvents=["ORDER_CANCELLED"],
                    query=_ORDER_SUBSCRIPTION,
                    targetUrl=f"{wh}/order-cancelled",
                ),
            ],
        )


_CUSTOMER_SUBSCRIPTION = (
    "subscription { event { ... on CustomerCreated { user { "
    "id email firstName lastName "
    "defaultBillingAddress { firstName lastName companyName streetAddress1 streetAddress2 "
    "city postalCode country { code } phone } "
    "defaultShippingAddress { firstName lastName companyName streetAddress1 streetAddress2 "
    "city postalCode country { code } phone } "
    "} } ... on CustomerUpdated { user { "
    "id email firstName lastName "
    "defaultBillingAddress { firstName lastName companyName streetAddress1 streetAddress2 "
    "city postalCode country { code } phone } "
    "defaultShippingAddress { firstName lastName companyName streetAddress1 streetAddress2 "
    "city postalCode country { code } phone } "
    "} } } }"
)

_ORDER_SUBSCRIPTION = (
    "subscription { event { "
    "... on OrderCreated { order { ...OrderData } } "
    "... on OrderConfirmed { order { ...OrderData } } "
    "... on OrderFullyPaid { order { ...OrderData } } "
    "... on OrderCancelled { order { ...OrderData } } "
    "} } "
    "fragment OrderData on Order { "
    "id number created "
    "user { id email firstName lastName } userEmail "
    "billingAddress { firstName lastName companyName streetAddress1 streetAddress2 city "
    "postalCode country { code } phone } "
    "shippingAddress { firstName lastName companyName streetAddress1 streetAddress2 city "
    "postalCode country { code } phone } "
    "lines { id productName variantName productSku quantity "
    "unitPrice { net { amount currency } gross { amount currency } tax { amount } } "
    "undiscountedUnitPrice { gross { amount } } unitDiscount { amount } "
    "totalPrice { net { amount } gross { amount } tax { amount } } taxRate "
    "variant { id sku } } "
    "shippingPrice { net { amount } gross { amount } tax { amount } } shippingMethodName "
    "discounts { valueType value amount { amount } reason } voucherCode "
    "total { net { amount } gross { amount currency } tax { amount } } status paymentStatus "
    "}"
)
