# Runbook — Bulk seed catalog Odoo → Saleor

Initial export of the catalog from Odoo to Saleor, followed by incremental
sync via webhooks. See ADR-0011..0014.

## Architecture (reverse flow)

```
Odoo product.template/category  ──base.automation──▶ ir.actions.server (code)
   │ _saleor_dispatch() writes saleor.outbox + POST
   ▼
POST {middleware}/api/odoo-events?secret=…   (ADR-0011)
   │ validate secret → enqueue arq (defer ~3s, dedup by model+id) → 200
   ▼
arq worker: sync_odoo_record_to_saleor
   fetch from Odoo (JSON-2) → resolve binding → Saleor mutation → upsert saleor.binding
```

Bulk seed bypasses the webhook flow and pushes the whole catalog itself (ADR-0013).

## Preconditions

1. **Both sides are running:**
   ```bash
   docker compose up -d
   ```
   Plus your own Saleor instance, started separately and reachable at
   `BRIDGE_SALEOR_API_URL` (default `http://localhost:8000/graphql/`) — this
   repo does not ship a Saleor stack.
2. **Odoo is configured** (saleor_sync v0.2 installed, catalog imported):
   ```bash
   .venv/bin/python scripts/odoo_setup.py        # imports the catalog (products + categories)
   ```
3. **Odoo API key** in `.env` (`BRIDGE_ODOO_API_KEY`) — via `scripts/generate_api_key.py`.
4. **Webhook secret** matching on both sides:
   ```
   BRIDGE_ODOO_WEBHOOK_SECRET=<32+ random characters>
   ```
   After editing `.env`, recreate the containers (NOT `restart`):
   ```bash
   docker compose up -d odoo middleware middleware-worker
   ```
   If saleor_sync was already installed, upgrade it so post_init writes the
   config-param:
   ```bash
   docker compose exec odoo odoo -c /tmp/odoo.conf -d marketplace -u saleor_sync --stop-after-init
   docker compose restart odoo
   ```
5. **Bridge Saleor App installed** (gives the middleware permission to write to Saleor):
   ```bash
   # the public URL must be reachable from the Saleor container:
   #   BRIDGE_MIDDLEWARE_PUBLIC_URL=http://host.docker.internal:8080
   .venv/bin/python scripts/install_bridge_app.py
   docker compose exec redis redis-cli KEYS 'saleor_bridge:apl:*'   # should return a key
   ```

## Seed

```bash
# 1. Plan (read-only, changes nothing):
docker compose exec middleware python -m saleor_bridge.cli.bulk_seed bulk-seed --dry-run

# 2. (optional, DESTRUCTIVE) wipe the existing Saleor catalog:
docker compose exec middleware python -m saleor_bridge.cli.bulk_seed wipe --yes

# 3. Real run (idempotent):
docker compose exec middleware python -m saleor_bridge.cli.bulk_seed bulk-seed
```

Expected result: 1 ProductType + all categories + all products, published in
`default-channel` with a price in your configured currency. In Odoo,
`saleor.binding` will show one `state='synced'` record per synced item.

Re-running `bulk-seed` does NOT create duplicates — it updates existing
records (looked up via `saleor.binding.odoo_id`).

## Verification (Saleor GraphQL, via the bridge-app token)

```bash
docker compose exec middleware python - <<'PY'
import asyncio, os, json
from saleor_bridge.adapters.saleor.factory import get_saleor_client
from saleor_bridge.config import get_settings
async def main():
    c = await get_saleor_client(get_settings())
    q='{ categories(first:100){totalCount} products(first:100){totalCount edges{node{name variants{sku}}}} }'
    print(json.dumps((await c.execute(q))['data'], ensure_ascii=False)[:1500])
asyncio.run(main())
PY
```

## Incremental sync (after seed)

Change a product's name/price in Odoo → `base.automation` → outbox →
middleware → Saleor within ~5s. Verify by opening the Saleor Dashboard or
re-running the GraphQL query above.

## Troubleshooting

| Symptom | Cause | What to do |
|---|---|---|
| `NoSaleorToken` in CLI | bridge-app not installed / token expired | `python scripts/install_bridge_app.py`, check the APL key |
| `PermissionDenied: MANAGE_PRODUCTS` | App missing permission (old/removed) | reinstall the app, see precondition 5 |
| `channel 'default-channel' not found` | App missing MANAGE_CHANNELS | reinstall the app (PERMISSIONS include MANAGE_CHANNELS) |
| 401 from `/api/odoo-events` | secret mismatch | compare `saleor_sync.webhook_secret` (Odoo) and `BRIDGE_ODOO_WEBHOOK_SECRET` (middleware) |
| webhook never arrives | automation disabled / Odoo can't reach the middleware | check base.automation is active; `BRIDGE_MIDDLEWARE_INTERNAL_URL=http://middleware:8080` |
| seed created duplicates | binding got wiped | remove duplicates via `wipe`, re-run seed |

## Force-resync a single product

```bash
# via Odoo shell — touch write_date, which triggers the automation:
docker compose exec odoo odoo shell -c /tmp/odoo.conf -d marketplace <<'PY'
env['product.template'].browse(7).write({'name': env['product.template'].browse(7).name})
env.cr.commit()
PY
```
