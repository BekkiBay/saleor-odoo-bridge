"""FastAPI entry-point."""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager

import redis.asyncio as redis
import structlog
from fastapi import FastAPI

from saleor_bridge import __version__
from saleor_bridge.api import health, manifest, odoo_events, register, webhooks
from saleor_bridge.config import get_settings
from saleor_bridge.queue.pool import make_arq_pool


def _configure_logging(level: str) -> None:
    """Structlog → JSON for prod, pretty for dev."""
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer()
            if level.upper() == "DEBUG"
            else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.redis = redis.from_url(settings.redis_url, decode_responses=True)
    app.state.arq_pool = await make_arq_pool(settings.redis_url)
    log = structlog.get_logger()
    log.info("lifespan_startup", redis=settings.redis_url)
    yield
    await app.state.arq_pool.aclose()
    await app.state.redis.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    _configure_logging(settings.log_level)

    app = FastAPI(
        title="Saleor ↔ Odoo Bridge",
        version=__version__,
        description="Bidirectional Saleor ↔ Odoo sync for orders, customers, products, and stock.",
        lifespan=lifespan,
    )

    app.include_router(health.router)
    app.include_router(manifest.router, prefix="/api")
    app.include_router(register.router, prefix="/api")
    app.include_router(odoo_events.router, prefix="/api")
    app.include_router(webhooks.router, prefix="/api/webhooks")

    log = structlog.get_logger()
    log.info(
        "middleware_started",
        version=__version__,
        public_url=settings.middleware_public_url,
        saleor_api_url=settings.saleor_api_url,
        odoo_url=settings.odoo_url,
    )
    return app


app = create_app()
