import os

from . import models


def post_init_setup_config_parameters(env):
    """Дефолтные config parameters для saleor_sync (Phase 3.2).

    middleware_url + webhook_secret берутся из env Odoo-контейнера; см.
    docker-compose (odoo service). webhook_secret обязан совпадать с
    BRIDGE_ODOO_WEBHOOK_SECRET у middleware.
    """
    icp = env["ir.config_parameter"].sudo()
    icp.set_param(
        "saleor_sync.middleware_url",
        os.environ.get("BRIDGE_MIDDLEWARE_INTERNAL_URL", "http://middleware:8080"),
    )
    icp.set_param(
        "saleor_sync.webhook_secret",
        os.environ.get("BRIDGE_ODOO_WEBHOOK_SECRET", ""),
    )
