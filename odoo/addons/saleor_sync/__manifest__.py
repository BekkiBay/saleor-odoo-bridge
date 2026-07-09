# See README.rst and ../../docs/decisions.md
{
    "name": "Saleor Sync",
    "version": "19.0.0.6.0",
    "category": "Sales",
    "summary": "Bidirectional sync with Saleor: catalog, stock, orders, customers",
    "license": "LGPL-3",
    "author": "saleor-odoo-bridge contributors",
    "website": "https://github.com/BekkiBay/saleor-odoo-bridge",
    "depends": [
        "sale_management",
        "stock",
        "stock_delivery",   # carrier_tracking_ref on stock.picking
        "account",
        "base_automation",  # triggers for outbound webhooks
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/saleor_binding_views.xml",
        "views/saleor_outbox_views.xml",
        "views/sale_order_views.xml",
        "data/ir_actions_server_data.xml",
        "data/base_automation_data.xml",
    ],
    "post_init_hook": "post_init_setup_config_parameters",
    "application": False,
    "installable": True,
    "auto_install": False,
}
