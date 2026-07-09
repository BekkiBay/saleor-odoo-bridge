# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] — 2026-07-09

The first release intended for anyone other than its original deployment.
Everything specific to that deployment has been removed, and the parts that
would have leaked into a stranger's Saleor store or Odoo database are fixed.

### ⚠️ Breaking

- **Odoo fields renamed.** `sale.order.justix_status` → `fulfillment_status`,
  `sale.order.justix_delivered` → `delivered_to_customer`. The Saleor order
  metadata key changed to match: `justix_status` → `fulfillment_status`.
  A migration (`migrations/19.0.0.6.0/pre-migrate.py`) renames the column so
  manually recorded delivery flags survive, drops the stale computed column,
  and retires the old external IDs. **Upgrade the addon
  (`-u saleor_sync`) rather than reinstalling it**, or the migration will not
  run. Storefronts reading the old metadata key must be updated.
- **`GET /ready` now returns HTTP 503 when Redis or Odoo is unreachable**,
  instead of always returning 200. Its docstring had promised this all along.
  Anything using `/ready` as a liveness probe should use `/health` instead.
- **`typer` and `rich` moved to the `cli` extra.** The webhook sync path never
  imported them. Install with `pip install "saleor-bridge[cli]"` to keep using
  `python -m saleor_bridge.cli.bulk_seed`.
- **Compose no longer pins `container_name`.** Containers are now named after
  the compose project, so two stacks can coexist. Scripts that referenced
  `marketplace-middleware` should use `docker compose exec middleware`.

### Fixed

- **Ops alert emails were never sent.** `queue/tasks.py` called
  `send_email_alert()` without `smtp_host`, so every alert hit the
  "no ops_email or smtp_host" early-return and was silently dropped. SMTP
  settings and the sender address are now passed through from config.
- **`bulk-seed` refused to run against a non-UZS Saleor channel**, emitting a
  hardcoded currency error. Odoo prices are now pushed verbatim and the channel
  currency is reported in the summary.
- **Russian strings were written into the connected Odoo database** — the
  shipping order line (`"Доставка"`), the discount note on every order with a
  voucher, and the divergence message posted to product chatter. All are
  English now.
- **`sync_order` could pass `None` as an order id** when the Odoo order was not
  found during total verification. It now reports the failure instead.
- `stock_picking` could pass `None` product ids to `read()`.

### Changed

- **App identity is configurable.** `GET /api/manifest` served a hardcoded app
  id, name, homepage and support email belonging to the original deployment, to
  every Saleor instance that installed it. These now come from
  `BRIDGE_APP_*` environment variables.
- Currency no longer defaults to `UZS` anywhere in the domain model.
- Odoo provisioning (`scripts/odoo_setup.py`) is now a generic installer:
  database, modules, company, verification. Locale, currency, country and
  timezone come from `.env` and default to `en_US`/`USD`/`US`/`UTC`.
- `mypy src` passes cleanly (was 148 errors under an aspirational
  `strict = true` that the code never satisfied). `strict` remains the goal.
- Documentation, code comments and log messages translated to English.

### Added

- CI (GitHub Actions): ruff, mypy and pytest on Python 3.11 and 3.12, the Odoo
  addon's unit tests, and `docker compose config` validation.
- `CONTRIBUTING.md`, this changelog, and tests covering `/ready` semantics,
  manifest identity, and the 0.2.0 migration (including the case where losing
  the delivery flags would otherwise go unnoticed).
- `BRIDGE_APP_*` and `ODOO_CURRENCY` / `ODOO_COUNTRY` / `ODOO_TIMEZONE` /
  `ODOO_LANG` settings.

### Removed

- Dead code: `queue/redis_queue.py` (superseded by arq), `domain/events.py`
  (never imported), the empty `ir_actions_server.py` placeholder, and the
  unused `BRIDGE_STOCK_RECONCILE_INTERVAL` setting (the reconcile job runs on a
  fixed cron).
- Catalog-bootstrap tooling belonging to the original store: the xlsx importer
  (`scripts/lib/products.py`, `categories.py`) and a bespoke Odoo list view
  (`scripts/lib/views.py`).
- Internal planning documents: a phase-by-phase research doc and a dated
  hardening log.

## [0.1.0] — 2026-07-05

- Initial public extraction from a production single-seller marketplace.
  FastAPI middleware, Odoo 19 `saleor_sync` addon, docker-compose stack,
  27 ADRs, ops runbooks.

[0.2.0]: https://github.com/BekkiBay/saleor-odoo-bridge/releases/tag/v0.2.0
[0.1.0]: https://github.com/BekkiBay/saleor-odoo-bridge/releases/tag/v0.1.0
