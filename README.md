# saleor-odoo-bridge

[![CI](https://github.com/BekkiBay/saleor-odoo-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/BekkiBay/saleor-odoo-bridge/actions/workflows/ci.yml)
[![License: LGPL v3](https://img.shields.io/badge/License-LGPL_v3-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)

Two-way sync bridge between [Saleor](https://github.com/saleor/saleor) (e-commerce) and [Odoo](https://github.com/odoo/odoo) (ERP): products, variants, categories, attributes, stock, orders and customers.

Extracted from a production single-seller marketplace. Runs against **Saleor 3.23** and **Odoo 19 Community**.

> **Status: beta.** Battle-tested in one production deployment. Issues and PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

## What it does

| Direction | Entities |
|---|---|
| Saleor → Odoo | customers (`res.partner` upsert by email), orders (`sale.order` draft → confirm on payment → cancel) |
| Odoo → Saleor | categories, attributes, products, variants (SKU as natural key), per-variant channel pricing, stock levels, order status |
| Both | stock reconciliation cron, conflict resolution, idempotent replays |

Reliability features:

- **Fail-closed webhook auth** — JWS verification for Saleor webhooks, shared-secret for Odoo webhooks; the middleware answers 503 on a missing or legacy secret.
- **Idempotency** — Redis `SET NX` dedup on inbound events, an outbox table on the Odoo side (`saleor.outbox`), and skip-guards against sync loops.
- **Retries + alerting** — 3 attempts with exponential backoff, then a Slack/email alert and `sync_state='failed'` on the binding record.
- **Stock safety buffer** and a periodic reconcile job to keep Saleor stock consistent with Odoo.

## Architecture

```
Saleor ──webhooks──▶ FastAPI middleware ──JSON-RPC──▶ Odoo
   ▲                  (JWS verify → idempotency        │
   │                   → Redis/arq queue → usecase)    │
   └───GraphQL mutations◀── arq worker ◀──webhooks─────┘
                                          (saleor_sync addon, outbox)
```

The middleware is hexagonal (ports & adapters): `adapters/saleor/` and `adapters/odoo/` translate to and from pure pydantic domain models in `domain/`; business logic lives in `usecases/`. Adding another storefront (Shopify, say) means adding one adapter package.

## Repository layout

| Path | What |
|---|---|
| `middleware/` | FastAPI + [arq](https://github.com/python-arq/arq) worker (Python 3.11+, `saleor_bridge` package) with a full pytest suite |
| `odoo/addons/saleor_sync/` | Odoo 19 addon: bindings, outbox, order-status automation |
| `docker-compose.yml` | Postgres 16 + Odoo 19 + Redis + middleware + worker |
| `scripts/` | Odoo provisioning and Saleor app registration, over JSON-RPC and GraphQL |
| `docs/adr/` | 27 architecture decision records |
| `docs/runbooks/` | Ops runbooks: key rotation, reconcile, smoke tests, order lifecycle |

## Quick start

Requirements: Docker 24+ with Compose v2, Python 3.11+, and a running Saleor instance (default: `http://localhost:8000`). This repo does not ship a Saleor stack — point `BRIDGE_SALEOR_API_URL` at your own.

```bash
cp .env.example .env    # fill in the values — see the comments inside
docker compose up -d    # Postgres + Odoo + Redis + middleware + worker
open http://localhost:8069

# Provision Odoo: database, modules, company, verification checks
python3 -m venv .venv && source .venv/bin/activate
pip install -r scripts/requirements.txt
python scripts/odoo_setup.py --reset
python scripts/generate_api_key.py     # writes BRIDGE_ODOO_API_KEY into .env
```

Then register the bridge as a Saleor App:

```bash
python scripts/install_bridge_app.py
```

Health checks: `curl http://localhost:8080/health` (always 200, reports each dependency) and `curl http://localhost:8080/ready` (503 unless Redis and Odoo both answer).

Set the `BRIDGE_APP_*` variables in `.env` before installing — they are what Saleor shows on the App install screen.

### Running the tests

```bash
cd middleware && pip install -e ".[dev]" && pytest    # 168 tests
cd .. && pytest odoo/addons/saleor_sync/tests/        # 15 tests, no Odoo runtime needed
```

## Known limitations

These are deliberate scope decisions from the original deployment, each recorded in an ADR. They are also the most useful things to contribute:

- **One Saleor channel** (ADR-0004) and **one ProductType** for the whole catalog (ADR-0012).
- **One Odoo warehouse** — `fetch_default_warehouse` takes the first one (ADR-0015).
- **No refund sync** (ADR-0009). Refunds are handled in the payment provider and Odoo separately.
- **Category re-parenting is not propagated** — the Saleor API has no move mutation (ADR-0006). The binding is marked `diverged` and logged.
- `saleor-bridge wipe` deletes **every** product and root category in the target Saleor instance, not just the synced ones.

## Documentation

- [`docs/adr/`](docs/adr/) — why it is built this way (SKU as natural key, outbox, skip-guards, safety buffer, …)
- [`docs/runbooks/`](docs/runbooks/) — day-2 operations
- [`docs/setup-odoo.md`](docs/setup-odoo.md) — standing up Odoo by hand
- [`middleware/README.md`](middleware/README.md) — middleware internals, ngrok setup, troubleshooting
- [`CHANGELOG.md`](CHANGELOG.md) — release notes; **0.2.0 renames two Odoo fields**, read it before upgrading

## License

[LGPL-3.0-or-later](LICENSE) — the same family as Odoo Community, so the Odoo addon can be used and modified freely.
