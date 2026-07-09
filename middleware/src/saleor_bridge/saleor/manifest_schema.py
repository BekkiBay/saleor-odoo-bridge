"""Pydantic schema for the Saleor App Manifest.

Reference: https://docs.saleor.io/developer/extending/apps/architecture/manifest
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from saleor_bridge import __version__
from saleor_bridge.config import Settings


class WebhookManifest(BaseModel):
    name: str
    targetUrl: str
    query: str
    asyncEvents: list[str] = []
    syncEvents: list[str] = []
    isActive: bool = True


class AppManifest(BaseModel):
    """The subset of manifest fields this bridge advertises."""

    id: str = "saleor-odoo-bridge"
    version: str = __version__
    name: str = "Saleor Odoo Sync"
    about: str = "Bidirectional sync between an Odoo back-office and a Saleor storefront."

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
    homepageUrl: str = "https://github.com/BekkiBay/saleor-odoo-bridge"
    supportUrl: str = "https://github.com/BekkiBay/saleor-odoo-bridge/issues"

    extensions: list[dict] = []
    webhooks: list[WebhookManifest] = []

    requiredSaleorVersion: str = "^3.20"
    author: str = "saleor-odoo-bridge contributors"

    @classmethod
    def build(cls, public_url: str, settings: Settings | None = None) -> AppManifest:
        """Manifest with the public URL substituted and all 6 webhooks declared.

        App identity (id/name/about/urls/author) comes from ``settings`` when
        given, so a deployment can advertise itself without patching the code.
        """
        base = public_url.rstrip("/")
        wh = f"{base}/api/webhooks"
        identity: dict[str, Any] = (
            {
                "id": settings.app_id,
                "name": settings.app_name,
                "about": settings.app_about,
                "homepageUrl": settings.app_homepage_url,
                "supportUrl": settings.app_support_url,
                "author": settings.app_author,
            }
            if settings is not None
            else {}
        )
        return cls(
            **identity,
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
