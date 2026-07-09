# saleor-bridge — middleware

FastAPI service + [arq](https://github.com/python-arq/arq) worker sitting between
Saleor and Odoo. Syncs customers and orders Saleor → Odoo, and catalog, stock and
order status Odoo → Saleor.

See [`../docs/decisions.md`](../docs/decisions.md) for the architecture decision records.

## What it does

**Endpoints (FastAPI):**

- `GET /health` — liveness. Always 200; reports Redis/Odoo state per dependency.
- `GET /ready` — readiness. **503** unless Redis and Odoo both answer.
- `GET /api/manifest` — Saleor App manifest (6 webhook subscriptions).
- `POST /api/register` — token exchange after `appInstall`.
- `POST /api/webhooks/{event}` — webhook receivers: JWS verify → idempotency
  (Redis `SET NX`, 24 h) → enqueue arq job → 200.
- `POST /api/odoo-events` — inbound Odoo events, authenticated with a shared secret.

**Worker (arq):**

- `CUSTOMER_CREATED` / `CUSTOMER_UPDATED` → upsert `res.partner` (matched by email,
  plus invoice/delivery child addresses).
- `ORDER_CREATED` → `sale.order` draft (ensures the customer, resolves products by SKU).
- `ORDER_CONFIRMED` → no-op (waits for payment, ADR-0005).
- `ORDER_FULLY_PAID` → `action_confirm` → state `sale`.
- `ORDER_CANCELLED` → `action_cancel` → state `cancel`.
- Odoo → Saleor: categories, attributes, products, variants, per-variant channel
  pricing, stock levels, order status metadata.
- Retries: 3 attempts with exponential backoff. After the last one → Slack + email
  alert and `saleor.binding.sync_state='failed'` (ADR-0008).

**Architecture (hexagonal / ports & adapters):**

```
adapters/saleor/  — payload → domain (Saleor-specific)
domain/           — pure pydantic models (platform-independent)
usecases/         — business logic (sync_customer, sync_order, …)
adapters/odoo/    — domain → JSON-2 calls (Odoo-specific)
```

Adding another storefront (Shopify, say) means adding `adapters/shopify/` and
leaving everything else alone.

```
Saleor ──webhook──▶ FastAPI (/api/webhooks/{event})
                    JWS verify → idempotency → enqueue arq → 200
                                                      │
                                          Redis ◀─────┘
                                            │
                              arq worker ◀──┘
                              payload → domain → usecase
                                            │ JSON-2 (bearer api key)
                                            ▼
                                          Odoo (res.partner, sale.order, …)
```

## Requirements

- Python **3.11+**
- Docker 24+ (for the compose stack)
- A public URL for Saleor webhooks (ngrok / Cloudflare Tunnel)

## Quick start — docker compose

From the repository root:

```bash
cp .env.example .env     # fill in the values
docker compose up -d     # db + odoo + redis + middleware + worker

curl http://localhost:8080/health
curl http://localhost:8080/api/manifest
```

## Local development (no Docker)

```bash
cd middleware
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Load the root .env into the environment:
set -a; source ../.env; set +a

# Redis is required — run it separately:
docker run -p 6379:6379 -d redis:7-alpine

uvicorn saleor_bridge.main:app --reload --port 8080
```

The bulk-seed CLI lives behind an extra: `pip install -e ".[cli]"`.

## Tests

```bash
cd middleware
pip install -e ".[dev]"
pytest -q
```

Coverage includes JWS signature verification, idempotency and skip-guards,
order/customer/product/variant/stock mapping, order financials, reconcile diffs,
readiness semantics, and manifest generation.

## Exposing the middleware to Saleor

Saleor must reach the middleware over the internet to deliver webhooks. Locally,
tunnel it:

```bash
ngrok http 8080
```

Copy the HTTPS URL into `.env`:

```
BRIDGE_MIDDLEWARE_PUBLIC_URL=https://abc123.ngrok-free.app
```

**Note:** on ngrok's free tier the URL changes on every restart. After a restart:

1. Update `BRIDGE_MIDDLEWARE_PUBLIC_URL` in `.env`.
2. `docker compose restart middleware`.
3. Re-register the App in Saleor (`appInstall` with the new manifest URL).

**Alternative — Cloudflare Tunnel** gives a stable URL without a paid tier: create a
tunnel in Cloudflare Zero Trust, run `cloudflared tunnel create saleor-bridge`, and
route DNS to `localhost:8080`.

## Installing the App in Saleor

Check the manifest is reachable from outside:

```bash
curl https://<your-public-url>/api/manifest
```

It should return JSON with `id`, `permissions` and `webhooks`. The app's identity
(`id`, name, homepage, support URL, author) comes from the `BRIDGE_APP_*` variables
in `.env` — set them to your own before installing.

Then either use the Saleor Dashboard (Apps → install from URL), run
`python scripts/install_bridge_app.py` from the repository root, or call the
mutation directly:

```graphql
mutation {
  appInstall(input: {
    appName: "Saleor Odoo Sync"
    manifestUrl: "https://<your-public-url>/api/manifest"
    permissions: [MANAGE_ORDERS, MANAGE_PRODUCTS, MANAGE_USERS,
                  MANAGE_PRODUCT_TYPES_AND_ATTRIBUTES, MANAGE_CHANNELS]
  }) {
    appInstallation { id status }
    errors { field message }
  }
}
```

Saleor fetches the manifest, POSTs a token to `/api/register`, and the middleware
stores it in the Redis APL, where the worker and the CLI read it from.

## Enqueueing a job by hand

Useful when you want to exercise the worker without driving Saleor:

```bash
docker compose exec -T middleware python -c "
import asyncio
from saleor_bridge.queue.pool import make_arq_pool
from saleor_bridge.config import get_settings
cust={'event':{'user':{'id':'VXNlcjox','email':'a@example.com','firstName':'A','lastName':'B',
  'defaultBillingAddress':{'streetAddress1':'St 1','city':'Springfield','country':{'code':'US'},'phone':'+15551112233'}}}}
order={'event':{'order':{'id':'T3JkZXI6MQ==','number':'1001','userEmail':'a@example.com',
  'lines':[{'productName':'X','productSku':'SKU-001','quantity':2,'unitPrice':{'gross':{'amount':'45.00','currency':'USD'}},'variant':{'sku':'SKU-001'}}],
  'total':{'gross':{'amount':'90.00','currency':'USD'}}}}}
async def m():
    p=await make_arq_pool(get_settings().redis_url)
    await p.enqueue_job('process_customer_created',cust); await asyncio.sleep(2)
    await p.enqueue_job('process_order_created',order); await asyncio.sleep(2)
    await p.enqueue_job('process_order_paid',order)
    await p.aclose()
asyncio.run(m())
"
docker compose logs -f middleware-worker   # customer_synced / order_created / order_confirmed
```

Then check Odoo: Contacts → a new partner; Sales → a new order (draft → sale once paid).

## Troubleshooting

**`/ready` returns 503, or `/health` shows `"redis": "fail"` / `"odoo": "fail"`**
The middleware cannot reach a dependency. From inside compose, use the service names —
`BRIDGE_REDIS_URL=redis://redis:6379/0`, `BRIDGE_ODOO_URL=http://odoo:8069`. From local
dev, `redis://localhost:6379/0` and `http://localhost:8069`.

**`/api/odoo-events` returns 503**
`BRIDGE_ODOO_WEBHOOK_SECRET` is empty or still set to the legacy placeholder. The
endpoint fails closed rather than trusting a publicly known secret.

**A self-hosted Saleor is unreachable from the middleware container**
On macOS/Windows use `http://host.docker.internal:8000/graphql/`. On Linux the compose
file already adds `extra_hosts: ["host.docker.internal:host-gateway"]`.

**JWKS endpoint not found (404)**
Saleor 3.5+ serves it at `{shop_url}/.well-known/jwks.json`. If a reverse proxy
intercepts `/.well-known/*`, let it through.

**`Saleor-Signature` header is empty**
The webhook is probably in legacy HMAC mode (a `secretKey` is set). Only JWS is
supported — create the webhook without `secretKey`. See ADR-0002.

**A sync failed and nothing obvious is in the logs**
Check the `saleor.binding` record in Odoo: `sync_state` and `error_message` carry the
reason. Set `BRIDGE_LOG_LEVEL=DEBUG` for structured JSON logs of every call.
