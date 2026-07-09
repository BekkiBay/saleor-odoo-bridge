# Runbook — Smoke test Saleor → Middleware → Odoo (local, without ngrok)

Proves the chain works end-to-end using a **real Saleor instance with a real
JWS signature** (not a direct enqueue). Local-only: Saleor and the middleware
run on the same machine and talk via `host.docker.internal`. **Works out of
the box on macOS.**

Automated one-command run:

```bash
.venv/bin/python scripts/smoke_test.py            # exit 0 = OK; the App is removed at the end
.venv/bin/python scripts/smoke_test.py --keep-app # keep the App around for inspection
```

Below is the manual version, with an explanation of each step.

## Preconditions

1. **Containers are up** — this stack, plus your own Saleor instance:
   ```bash
   docker compose up -d        # db, odoo, redis, middleware, middleware-worker
   ```
   Also start your own Saleor instance (this bridge expects it reachable at
   `BRIDGE_SALEOR_API_URL`, default `http://localhost:8000/graphql/`) — this
   repo does not ship a Saleor stack.
2. **Odoo is configured** (saleor_sync installed):
   ```bash
   .venv/bin/python scripts/odoo_setup.py --reset
   # 15/15 checks, "5 modules installed: account, contacts, sale_management, saleor_sync, stock"
   ```
3. **Odoo API key** in `.env` (`BRIDGE_ODOO_API_KEY`):
   ```bash
   .venv/bin/python scripts/generate_api_key.py
   ```
4. **Middleware public URL** in `.env`:
   ```
   BRIDGE_MIDDLEWARE_PUBLIC_URL=http://host.docker.internal:8080
   ```
   After editing `.env`, recreate the containers (NOT `restart` — it doesn't
   reread env vars):
   ```bash
   docker compose up -d middleware middleware-worker
   ```

## Saleor-side configuration for local app install (IMPORTANT)

By default, Saleor blocks apps and their webhooks from installing against
local/private addresses. For a local smoke test, configure your own Saleor
instance to allow the bridge's public URL:

- **`HTTP_IP_FILTER_ENABLED=False`** — otherwise Saleor refuses to install an
  App whose manifest resolves to a private IP (`host.docker.internal` →
  something like `192.168.65.254`), failing with
  `Failed to install app. Error: 192.168.65.254`.
  ⚠️ This disables SSRF protection. **Local only. In production, keep it
  `True` and use a public HTTPS URL.**
- **`ALLOWED_HOSTS`** must include `host.docker.internal` — otherwise, when
  the middleware fetches JWKS from
  `http://host.docker.internal:8000/.well-known/jwks.json`, Django responds
  `400 DisallowedHost`.

After changing your Saleor instance's configuration, recreate its containers
so the new environment takes effect (env files are only read at container
creation) — refer to your own Saleor deployment's docs for the exact command.

## Steps

### 1. Health
```bash
curl http://localhost:8080/health                 # {"status":"ok","redis":"ok","odoo":"ok"}
```

### 2. Saleor admin token
Default Saleor populatedb superuser: `admin@example.com` / `admin`.
```bash
curl -s -X POST http://localhost:8000/graphql/ -H "Content-Type: application/json" \
  -d '{"query":"mutation{tokenCreate(email:\"admin@example.com\",password:\"admin\"){token errors{message}}}"}'
```

### 3. appInstall
```graphql
mutation {
  appInstall(input:{
    appName:"Saleor Odoo Sync (Smoke)"
    manifestUrl:"http://host.docker.internal:8080/api/manifest"
    activateAfterInstallation:true
    permissions:[MANAGE_ORDERS,MANAGE_PRODUCTS,MANAGE_USERS,MANAGE_PRODUCT_TYPES_AND_ATTRIBUTES,MANAGE_CHANNELS]
  }){ appInstallation{ id status } errors{ field message permissions } }
}
```
Header: `Authorization: Bearer <admin_token>`. Poll `appsInstallations` until
`status=SUCCESS` (or it disappears from the list). If an App with this name
already exists, run `appDelete` first.

After installation, Saleor:
1. GETs `/api/manifest` (200),
2. POSTs `/api/register` → the middleware stores the token in Redis under
   `saleor_bridge:apl:<saleor_api_url>` (NOT `app:<domain>`),
3. creates 6 webhooks from the manifest.

Check:
```bash
docker compose exec redis redis-cli KEYS "saleor_bridge:apl:*"
```

### 4. Trigger CUSTOMER_CREATED
```graphql
mutation { customerCreate(input:{
  email:"smoke-test-<ts>@example.com" firstName:"Smoke" lastName:"Test"
}){ user{ id email } errors{ message } } }
```

### 5. Verification (~6s later)

**middleware** (`docker compose logs --tail=80 middleware`):
```
GET /api/manifest 200
register_ok ... POST /api/register 200
GET http://host.docker.internal:8000/.well-known/jwks.json 200
webhook_received signature_valid=true kid=... took_ms<200  (evt=CUSTOMER_CREATED)
```

**worker** (`docker compose logs --tail=80 middleware-worker`):
```
customer_synced created=True odoo_partner_id=<int> saleor_id=<base64>
```

**Odoo**:
```bash
.venv/bin/python scripts/verify_smoke.py
# partner name='Smoke Test' customer_rank=1; binding sync_state=synced, saleor_id set
```

### 6. Idempotency
`customerUpdate` (change `note` so Saleor actually sends CUSTOMER_UPDATED) →
Odoo does NOT create a duplicate (still 1 partner), `last_sync_in` is fresher.

### 7. Cleanup
`appDelete` for "Saleor Odoo Sync (Smoke)". `smoke_test.py` does this itself
(unless run with `--keep-app`). The smoke-test partner in Odoo is left in
place as evidence it worked.

## Known pitfalls (verified)

| Symptom | Cause | Fix |
|---|---|---|
| `restart` didn't pick up env changes | `docker compose restart` doesn't reread `.env`/`env_file` | `docker compose up -d <svc>` |
| `Failed to install app. Error: 192.168.65.254` | Saleor's SSRF IP filter blocks the private IP | `HTTP_IP_FILTER_ENABLED=False` (local only) |
| webhook 401 `jwks fetch failed: All connection attempts failed` | Saleor announces `localhost:8000`, unreachable from inside the container | the middleware fetches JWKS from `BRIDGE_SALEOR_API_URL` (host.docker.internal) instead |
| webhook 401 `400 DisallowedHost` on JWKS | `host.docker.internal` not in `ALLOWED_HOSTS` | add it to your Saleor instance's `ALLOWED_HOSTS` configuration |
| webhook 401 `bad_signature` | Saleor signs with RFC 7797 `b64:false`; the middleware's verifier expected `b64:true` | fixed in `signature.py` (supports `b64:false`) |
| odoo shell `${...}` not substituted | shell run with `-c /etc/odoo/odoo.conf` (raw `${}` in there) | use `/tmp/odoo.conf` (the entrypoint substitutes env vars into it) |

## Production — how it differs

- A public HTTPS URL (ngrok/Cloudflare/a real domain) instead of
  `host.docker.internal`.
- `HTTP_IP_FILTER_ENABLED=True`, the real domain listed in `ALLOWED_HOSTS`.
- Saleor's `PUBLIC_URL` = the public domain → `saleor-api-url` in webhooks is
  correct, so the middleware doesn't need a separate JWKS override.
