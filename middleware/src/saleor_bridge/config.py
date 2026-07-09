"""Settings — all via env vars prefixed with BRIDGE_."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Middleware config. Every field is set through a BRIDGE_* env var."""

    # ── Saleor ────────────────────────────────────────────────────────────
    saleor_api_url: str = Field(
        default="http://localhost:8000/graphql/",
        description="Saleor GraphQL endpoint.",
    )
    saleor_app_id: str = Field(default="", description="App ID after appInstall (optional).")
    saleor_app_token: str = Field(default="", description="App bearer token after registration.")
    saleor_default_channel: str = Field(
        default="default-channel",
        description="The single channel slug this bridge operates on (see ADR-0004).",
    )
    saleor_product_type_name: str = Field(
        default="Generic",
        description="Name of the single ProductType used for the catalog (see ADR-0012).",
    )

    # ── App identity (served by GET /api/manifest) ────────────────────────
    app_id: str = Field(default="saleor-odoo-bridge", description="Saleor App id in the manifest.")
    app_name: str = Field(default="Saleor Odoo Sync", description="App name shown in Saleor.")
    app_about: str = Field(
        default="Bidirectional sync between an Odoo back-office and a Saleor storefront.",
        description="App description shown on the Saleor install screen.",
    )
    app_homepage_url: str = Field(
        default="https://github.com/BekkiBay/saleor-odoo-bridge",
        description="Homepage URL advertised in the manifest.",
    )
    app_support_url: str = Field(
        default="https://github.com/BekkiBay/saleor-odoo-bridge/issues",
        description="Support URL advertised in the manifest.",
    )
    app_author: str = Field(
        default="saleor-odoo-bridge contributors",
        description="Author advertised in the manifest.",
    )

    # ── Odoo ──────────────────────────────────────────────────────────────
    odoo_url: str = "http://odoo:8069"
    odoo_db: str = "odoo"
    odoo_api_key: str = Field(default="", description="Odoo API key (Preferences → Account Security).")
    odoo_webhook_secret: str = Field(
        default="",
        description="Shared secret for inbound Odoo→middleware webhooks (see ADR-0011). "
        "MUST be set in production; an empty value (or the legacy 'changeme-please') makes "
        "/api/odoo-events return 503 rather than trust a publicly known secret.",
    )
    odoo_shipping_sku: str = Field(default="SHIPPING", description="default_code of the Odoo shipping service product.")
    order_total_tolerance: int = Field(
        default=1,
        description="Max |Odoo-Saleor| order total difference, in minor units of the channel "
        "currency, before the order is flagged as 'diverged'.",
    )

    # ── Middleware self ───────────────────────────────────────────────────
    middleware_public_url: str = Field(
        default="http://localhost:8080",
        description="Public URL that Saleor posts webhooks to (ngrok / Cloudflare Tunnel).",
    )
    log_level: str = "INFO"

    # ── Redis ─────────────────────────────────────────────────────────────
    redis_url: str = "redis://redis:6379/0"

    # ── Stock consistency (see ADR-0010, ADR-0016) ────────────────────────
    stock_safety_buffer: int = 1

    # ── Ops alerts (see ADR-0008); all optional, empty disables the channel ─
    slack_webhook_url: str = ""
    ops_email: str = ""
    alert_from_email: str = Field(
        default="saleor-bridge@localhost",
        description="From: address used for ops alert emails.",
    )
    smtp_host: str = ""
    smtp_port: int = 25
    smtp_user: str = ""
    smtp_password: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="BRIDGE_",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """FastAPI Dependency-friendly accessor. lru-cached — read once."""
    return Settings()
