============
Saleor Sync
============

Odoo-side half of the bidirectional sync between Odoo and Saleor.

This module keeps Odoo's catalog, stock, and order state in sync with a
Saleor storefront, via the ``saleor-odoo-bridge`` middleware. It provides:

- ``saleor.binding`` — the external ID mapping table between Odoo records
  and Saleor objects (``model_name`` + ``odoo_id`` ↔ ``saleor_id``), with a
  ``sync_state`` (pending / synced / failed / diverged) and an
  ``error_message`` for the last failure (see ADR-0003, ADR-0007, ADR-0008).
- ``saleor.outbox`` — an audit/debug log of outbound events sent to the
  middleware, recording the payload, HTTP response code, and outcome
  (sent / confirmed / failed) for every dispatch.
- A ``sale.order`` extension: a computed, unified ``fulfillment_status``
  (five steps — paid, assembling, shipped, delivered, cancelled) plus a
  manually-set ``delivered_to_customer`` flag. Both are pushed to the Saleor
  order's metadata by the middleware so the storefront and Odoo always show
  the same status (see ADR-0019, ADR-0021).
- ``models/product_sync.py`` — dispatch logic that turns changes to
  ``product.template``, ``product.category``, ``product.attribute``,
  ``product.attribute.value``, ``product.product`` (variants),
  ``stock.quant``, ``sale.order`` state, and ``stock.picking`` into outbound
  events for the middleware (see ADR-0011, ADR-0017, ADR-0019, ADR-0023,
  ADR-0024, ADR-0026, ADR-0027).
- Server actions (``data/ir_actions_server_data.xml``) and
  ``base.automation`` rules (``data/base_automation_data.xml``) that fire on
  record create/write and call the dispatch logic above.
- A skip-guard context key, ``saleor_sync_skip``, that callers can set to
  suppress the outbound webhook for a given write — used so that writes
  originating from Saleor-side events do not echo straight back to Saleor
  (see ADR-0020).

Dependencies
============

- ``sale_management``
- ``stock``
- ``stock_delivery`` (``carrier_tracking_ref`` on ``stock.picking``)
- ``account``
- ``base_automation`` (triggers for the outbound webhooks)

Installation
=============

Via the UI:

1. Apps → Update Apps List.
2. Search for "Saleor Sync".
3. Install.

Or via the CLI:

.. code-block:: bash

   docker compose exec odoo odoo -d marketplace -i saleor_sync --stop-after-init

Configuration
=============

The module talks to the middleware over HTTP and authenticates with a
shared secret. Configuration is read through ``ir.config_parameter``, seeded
at install time by the ``post_init_setup_config_parameters`` post-init hook,
but the following environment variables take precedence whenever they are
set on the Odoo container (so rotating a secret and restarting takes effect
immediately, without reinstalling the module):

- ``BRIDGE_ODOO_WEBHOOK_SECRET`` — shared secret sent as a query parameter
  on every outbound POST to the middleware (falls back to the stored
  ``saleor_sync.webhook_secret`` parameter).
- ``BRIDGE_MIDDLEWARE_INTERNAL_URL`` — base URL of the middleware's internal
  API, e.g. ``http://middleware:8080`` (falls back to the stored
  ``saleor_sync.middleware_url`` parameter).

See also
========

- Repository root `README <../../../README.md>`_ for the overall
  architecture of the bridge (Odoo, middleware, Saleor).
- `ADR-0003: Odoo custom module <../../../docs/adr/0003-odoo-custom-module.md>`_
- `ADR-0007: SKU as natural key <../../../docs/adr/0007-sku-as-natural-key.md>`_
- `ADR-0008: Failed sync handling <../../../docs/adr/0008-failed-sync-handling.md>`_
- `ADR-0011: Secret in query for the Odoo webhook <../../../docs/adr/0011-secret-in-query-for-odoo-webhook.md>`_
- `ADR-0019: Order status mapping <../../../docs/adr/0019-order-status-mapping.md>`_
- `ADR-0020: Skip-guard mechanism <../../../docs/adr/0020-skip-guard-mechanism.md>`_
- `docs/adr <../../../docs/adr/>`_ for the full architecture decision log
