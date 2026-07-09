# Runbook — Odoo API key rotation (middleware)

The middleware talks to Odoo over the JSON-2 REST API (`/json/2/...`) with
`Authorization: bearer <BRIDGE_ODOO_API_KEY>`. The key is bound to the user
`admin@marketplace.local` (uid 2, an example login), **scope = NULL** (global
— required for JSON-2), TTL **3 months**.

## When to rotate

- About 1 week before expiry (see table below).
- On `.env` compromise / key leak.
- When the admin user changes.

| Created | Expires | Action |
|---|---|---|
| _(fill in)_ | _(fill in)_ | rotate ~1 week before expiry |

> Update this row on every rotation.

## Rotation

```bash
.venv/bin/python scripts/generate_api_key.py          # generates a new key, writes it to .env
docker compose up -d middleware middleware-worker      # pick up the new key (NOT restart)
curl http://localhost:8080/health                      # {"odoo":"ok"}
```

The script:
1. Deletes old keys named `saleor-bridge-smoke` for the admin user (idempotent).
2. Generates a new one: `env['res.users.apikeys'].with_user(admin)._generate(None, 'saleor-bridge-smoke', now+3mo)`.
   - `_generate` binds the key to `self.env.user`, hence `with_user(admin)`.
   - scope `None` (NOT `'rpc'`) — the JSON-2 API requires a global-scope key.
3. Prints `BRIDGE_ODOO_API_KEY=<key>` and rewrites that line in `.env`.

Check it in the database:
```bash
docker compose exec db psql -U "${POSTGRES_USER:-odoo}" -d marketplace -tA -c \
  "SELECT name,user_id,scope,expiration_date FROM res_users_apikeys WHERE name='saleor-bridge-smoke';"
# saleor-bridge-smoke|2||<exp>     (empty scope = NULL)
```

## Gotchas

- **`odoo shell` isn't interactive in the script** — `generate_api_key.py`
  pipes code into
  `docker compose exec -T odoo odoo shell -d marketplace --no-http -c /tmp/odoo.conf`.
  The config must be `/tmp/odoo.conf` (the entrypoint substitutes env vars
  into it; `/etc/odoo/odoo.conf` still has raw `${...}` placeholders).
- **After writing to `.env`**, the middleware/worker must be **recreated**
  (`up -d`) — `restart` does not reread environment variables.
- **The key is shown only once** — after generation only its hash is stored
  in the DB. If you lose it, generate a new one.
