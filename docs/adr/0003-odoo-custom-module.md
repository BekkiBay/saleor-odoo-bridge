# ADR-0003: Custom Odoo module `saleor_sync`

## Status
Accepted (2026-05-21)

## Context

The middleware pushes data into Odoo through the JSON-2 REST API, but a few Odoo-side artifacts are needed:

1. **External ID mapping** — a table `(model, odoo_id, saleor_id, last_sync, state)`. Without it, every "find the sale.order for this Saleor ID" lookup becomes a full table scan on `client_order_ref` (slow, no uniqueness guarantee).

2. **Outbound webhooks** (catalog/stock/order-status changes pushed to Saleor) — Odoo 19 provides a native `ir.actions.server` with `state='webhook'` (see ADR-0001 and the integration research that informed these ADRs). Server actions are configured through the UI / XML data, which requires an Odoo module for versioning.

3. **Server-side ORM helpers** — methods like `sale.order.action_confirm_from_saleor()` (an atomic "confirm + invoice + post + register payment"). Each step as a separate JSON-2 call means a round trip and risk of a transient lock failure. A single server-side method means a single transaction.

4. **Future needs:** `queue_job` hooks, converters (EditorJS→HTML), migrations (XMLID fixtures).

## Decision

We create the Odoo Community module **`saleor_sync`** in `odoo/addons/saleor_sync/`. Standard layout: `__manifest__`, `models/`, `security/`, `views/`, `data/`.

Initially the module contains only a skeleton:
- the `saleor.binding` model (external ID mapping),
- ACLs for `saleor.binding`,
- a minimal tree/form view,
- an empty `data/ir_actions_server_data.xml` (a template for future server actions).

Business-logic methods, concrete `ir.actions.server` records, mapper helpers, and the EditorJS converter are added later, as the corresponding sync flows are built out.

Dependencies in `__manifest__.py`: `sale_management`, `stock`, `account`. **`queue_job` is not added as a dependency initially** (installing it requires the OCA repo, and we don't want to block the smoke test on that). It's added once it's actually needed — described in the README.

License: LGPL-3 (compatible with OCA in case of a future publication).

## Alternatives considered

1. **Use `ir.model.data` directly, without a dedicated table.** The standard Odoo external-id mechanism. **Rejected:** XMLID has no `last_sync_in/out/state/error` fields. A domain-specific state table is needed.

2. **Store the mapping in Redis on the middleware side.** **Rejected:** Odoo-side scripts/cron jobs have no access to Redis without a custom controller. The mapping needs to be visible to Odoo operators through Studio/the UI too.

3. **The `OCA/connector` framework.** Backend + Binding + Mapper pattern. **Rejected for now:** [no 19.0 port exists as of May 2026](https://github.com/OCA/connector). We can migrate once one is available.

## Consequences

**Pros:**
- Server actions and mappings are versioned in git (XML data files).
- Operators can see in the UI which records are being synced (the saleor_binding tree view).
- A future migration to OCA/connector would mean renaming models, not rewriting them.

**Cons:**
- A custom module install is required for every environment (dev/staging/prod).
- Upgrading Odoo (16→17→18→19→20) may require adjusting the module (Selection options, API changes).

**Mitigation:** the module version is pinned in `__manifest__.py` (`'19.0.0.1.0'`). A major Odoo version bump triggers a module review.
