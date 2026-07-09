"""Unit tests for the Saleor App Manifest."""

from __future__ import annotations

from saleor_bridge.config import Settings
from saleor_bridge.saleor.manifest_schema import AppManifest


def test_manifest_builds_with_substituted_urls():
    m = AppManifest.build(public_url="https://example.ngrok-free.app")

    assert m.appUrl == "https://example.ngrok-free.app"
    assert m.tokenTargetUrl == "https://example.ngrok-free.app/api/register"
    assert m.dataPrivacyUrl == "https://example.ngrok-free.app/legal/privacy"


def test_manifest_trims_trailing_slash():
    m = AppManifest.build(public_url="https://example.ngrok-free.app/")
    assert m.appUrl == "https://example.ngrok-free.app"
    assert m.tokenTargetUrl == "https://example.ngrok-free.app/api/register"


def test_manifest_has_six_webhooks():
    """2 customer + 4 order webhooks."""
    m = AppManifest.build(public_url="https://example.app")
    assert len(m.webhooks) == 6
    events = {ev for w in m.webhooks for ev in w.asyncEvents}
    assert events == {
        "CUSTOMER_CREATED", "CUSTOMER_UPDATED",
        "ORDER_CREATED", "ORDER_CONFIRMED", "ORDER_FULLY_PAID", "ORDER_CANCELLED",
    }


def test_manifest_webhook_target_urls():
    m = AppManifest.build(public_url="https://example.app")
    urls = {w.targetUrl for w in m.webhooks}
    assert "https://example.app/api/webhooks/order-created" in urls
    assert "https://example.app/api/webhooks/customer-created" in urls


def test_manifest_includes_required_permissions():
    m = AppManifest.build(public_url="https://example.app")
    assert "MANAGE_ORDERS" in m.permissions
    assert "MANAGE_PRODUCTS" in m.permissions
    assert "MANAGE_USERS" in m.permissions


def test_manifest_serializes_to_dict():
    """Saleor wants JSON object — model_dump should work."""
    m = AppManifest.build(public_url="https://example.app")
    d = m.model_dump(exclude_none=True)
    assert d["id"] == "saleor-odoo-bridge"
    assert "permissions" in d
    assert "webhooks" in d
    assert isinstance(d["webhooks"], list)


def test_manifest_identity_comes_from_settings():
    """A deployment advertises itself via env, without patching the code."""
    settings = Settings(
        app_id="com.acme.bridge",
        app_name="Acme Sync",
        app_about="Acme's bridge.",
        app_homepage_url="https://acme.example",
        app_support_url="mailto:ops@acme.example",
        app_author="Acme Inc",
    )
    m = AppManifest.build(public_url="https://example.app", settings=settings)
    assert m.id == "com.acme.bridge"
    assert m.name == "Acme Sync"
    assert m.homepageUrl == "https://acme.example"
    assert m.supportUrl == "mailto:ops@acme.example"
    assert m.author == "Acme Inc"
    # URLs still derive from the public URL, not from settings.
    assert m.tokenTargetUrl == "https://example.app/api/register"


def test_order_subscription_includes_financial_fields():
    m = AppManifest.build(public_url="https://example.app")
    order_wh = next(w for w in m.webhooks if "order-created" in w.targetUrl)
    q = order_wh.query
    for token in ["shippingPrice", "shippingMethodName", "taxRate",
                  "undiscountedUnitPrice", "discounts", "voucherCode", "net {"]:
        assert token in q, f"missing {token!r} in order subscription"
