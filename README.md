# saleor-odoo-bridge

Two-way sync bridge between [Saleor](https://github.com/saleor/saleor) (e-commerce) and [Odoo](https://github.com/odoo/odoo) (ERP): products, variants, categories, attributes, stock, orders and customers.

Extracted from a production single-seller marketplace. Runs against **Saleor 3.23** and **Odoo 19 Community**.

> **Status: beta.** Battle-tested in one production deployment; APIs and module layout may still change. Issues and PRs welcome.

## What it does

| Direction | Entities |
|---|---|
| Saleor → Odoo | customers (`res.partner` upsert by email), orders (`sale.order` draft → confirm on payment → cancel) |
| Odoo → Saleor | categories, attributes, products, variants (SKU as natural key), per-variant channel pricing, stock levels, order status |
| Both | stock reconciliation cron, conflict resolution, idempotent replays |

Reliability features:

- **Fail-closed webhook auth** — JWS verification for Saleor webhooks, shared-secret for Odoo webhooks; middleware answers 503 on missing/legacy secrets.
- **Idempotency** — Redis `SET NX` dedup on inbound events, outbox pattern on the Odoo side (`saleor.outbox`), skip-guards against sync loops.
- **Retries + alerting** — 3 attempts with exponential backoff, then Slack/email alert and `sync_state='failed'` on the binding record.
- **Stock safety buffer** and periodic reconcile to keep Saleor stock consistent with Odoo.

## Architecture

```
Saleor ──webhooks──▶ FastAPI middleware ──JSON-RPC──▶ Odoo
   ▲                  (JWS verify → idempotency        │
   │                   → Redis/arq queue → usecase)    │
   └───GraphQL mutations◀── arq worker ◀──webhooks─────┘
                                          (saleor_sync addon, outbox)
```

The middleware is hexagonal (ports & adapters): `adapters/saleor/` and `adapters/odoo/` translate to/from pure pydantic domain models in `domain/`; business logic lives in `usecases/`. Adding another storefront (e.g. Shopify) means adding one adapter package.

## Repository layout

| Path | What |
|---|---|
| `middleware/` | FastAPI + [arq](https://github.com/python-arq/arq) worker (Python 3.11, `saleor_bridge` package) with a full pytest suite |
| `odoo/addons/saleor_sync/` | Odoo 19 addon: bindings, outbox, order-status automation |
| `docker-compose.yml` | Postgres 16 + Odoo 19 + Redis + middleware stack |
| `scripts/` | Odoo bootstrap automation (DB creation, module install, catalog import) via JSON-RPC |
| `docs/adr/` | 27 architecture decision records |
| `docs/runbooks/` | Ops runbooks: key rotation, reconcile, smoke tests, order lifecycle |

## Quick start

Requirements: Docker 24+ with Compose v2, Python 3.11+, a running Saleor instance (default: `http://localhost:8000`).

```bash
cp .env.example .env    # fill in the values — see comments inside
docker compose up -d    # Postgres + Odoo + Redis + middleware
open http://localhost:8069

# optional: bootstrap Odoo (create DB, install modules) without clicking through the UI
python3 -m venv .venv && source .venv/bin/activate
pip install -r scripts/requirements.txt
python scripts/odoo_setup.py --reset
```

Then install the bridge as a Saleor App:

```bash
python scripts/install_bridge_app.py
```

Health check: `curl http://localhost:8080/health` (verifies Redis and Odoo connectivity).

### Running the middleware tests

```bash
cd middleware
pip install -e ".[dev]"
pytest
```

## Documentation

- [`docs/adr/`](docs/adr/) — why it is built this way (SKU as natural key, outbox, skip-guards, safety buffer, …)
- [`docs/runbooks/`](docs/runbooks/) — day-2 operations
- [`middleware/README.md`](middleware/README.md) — middleware internals
- Some documents are currently in Russian; translations are in progress.

## License

[LGPL-3.0-or-later](LICENSE) — same family as Odoo Community, so the Odoo addon can be used and modified freely.
