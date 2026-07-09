"""Settings — все через env vars с префиксом BRIDGE_."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Конфиг middleware. Все поля — через env vars BRIDGE_*."""

    # ── Saleor ────────────────────────────────────────────────────────────
    saleor_api_url: str = Field(
        default="http://localhost:8000/graphql/",
        description="Saleor GraphQL endpoint.",
    )
    saleor_app_id: str = Field(default="", description="App ID после appInstall (опционально).")
    saleor_app_token: str = Field(default="", description="App bearer token после регистрации.")
    saleor_default_channel: str = Field(
        default="default-channel",
        description="Channel slug для MVP (см. ADR-0004).",
    )
    saleor_product_type_name: str = Field(
        default="Generic",
        description="Имя единственного ProductType для каталога (ADR-0012).",
    )

    # ── Odoo ──────────────────────────────────────────────────────────────
    odoo_url: str = "http://odoo:8069"
    odoo_db: str = "marketplace"
    odoo_api_key: str = Field(default="", description="Odoo API key (Preferences → Account Security).")
    odoo_webhook_secret: str = Field(
        default="",
        description="Shared secret для входящих Odoo→middleware webhooks (ADR-0011). "
        "MUST быть задан в prod; пустой (или legacy 'changeme-please') → /api/odoo-events "
        "возвращает 503 и не доверяет публично-известному секрету.",
    )
    odoo_shipping_sku: str = Field(default="SHIPPING", description="default_code of the Odoo shipping service product.")
    order_total_tolerance: int = Field(default=1, description="Max |Odoo-Saleor| order total diff before 'diverged' (UZS).")

    # ── Middleware self ───────────────────────────────────────────────────
    middleware_public_url: str = Field(
        default="http://localhost:8080",
        description="Публичный URL для Saleor webhooks (ngrok/Cloudflare Tunnel).",
    )
    log_level: str = "INFO"

    # ── Redis ─────────────────────────────────────────────────────────────
    redis_url: str = "redis://redis:6379/0"

    # ── Stock consistency (Phase 3.3) ─────────────────────────────────────
    stock_safety_buffer: int = 1
    stock_reconcile_interval: int = 300

    # ── Ops alerts (Phase 3.1+) ───────────────────────────────────────────
    slack_webhook_url: str = ""
    ops_email: str = ""
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
    """FastAPI Dependency-friendly accessor. Lru-cached — читается один раз."""
    return Settings()
