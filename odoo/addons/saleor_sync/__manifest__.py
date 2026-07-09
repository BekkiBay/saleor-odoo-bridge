# See README.rst and ../../docs/decisions.md
{
    "name": "Saleor Sync",
    "version": "19.0.0.5.0",
    "category": "Sales",
    "summary": "Bidirectional sync with Saleor e-commerce (Phase 3.5: variants & attributes Odoo↔Saleor)",
    "license": "LGPL-3",
    "author": "Justix Market",
    "website": "https://justix.uz",
    "depends": [
        "sale_management",
        "stock",
        "stock_delivery",   # Phase 3.4: carrier_tracking_ref на stock.picking
        "account",
        "base_automation",  # Phase 3.2: триггеры outbound webhook'ов
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
