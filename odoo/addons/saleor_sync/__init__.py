import os

from . import models


def post_init_setup_config_parameters(env):
    """Seed the default config parameters for saleor_sync.

    middleware_url and webhook_secret are read from the Odoo container's
    environment; see docker-compose.yml (odoo service). webhook_secret must
    match BRIDGE_ODOO_WEBHOOK_SECRET on the middleware.
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
