# Runbook — Smoke test Saleor → Middleware → Odoo (local, без ngrok)

Доказывает что цепочка работает end-to-end через **настоящий Saleor с настоящей
подписью JWS** (не прямой enqueue). Local-only: Saleor и middleware на одной
машine, общаются через `host.docker.internal`. **macOS работает из коробки.**

Автоматический прогон одной командой:

```bash
cd odoo-saleor-integration
.venv/bin/python scripts/smoke_test.py            # exit 0 = OK; App удаляется в конце
.venv/bin/python scripts/smoke_test.py --keep-app # оставить App для инспекции
```

Ниже — ручная версия + объяснение каждого шага.

## Предусловия

1. **Контейнеры подняты** — оба стека:
   ```bash
   cd odoo-saleor-integration && docker compose up -d        # odoo, db, redis, middleware, middleware-worker
   cd ../saleor && docker compose up -d                       # saleor-api, worker, db, cache, ...
   ```
2. **Odoo настроен** (saleor_sync installed):
   ```bash
   cd odoo-saleor-integration && .venv/bin/python scripts/odoo_setup.py --reset
   # 15/15 checks, "5 modules installed: account, contacts, sale_management, saleor_sync, stock"
   ```
3. **Odoo API key** в `.env` (`BRIDGE_ODOO_API_KEY`):
   ```bash
   .venv/bin/python scripts/generate_api_key.py
   ```
4. **Middleware public URL** в `.env`:
   ```
   BRIDGE_MIDDLEWARE_PUBLIC_URL=http://host.docker.internal:8080
   ```
   После правки `.env` пересоздать (НЕ `restart` — он не перечитывает env):
   ```bash
   docker compose up -d middleware middleware-worker
   ```

## Saleor-side настройки для local app install (ВАЖНО)

Saleor по умолчанию блокирует приложения и их вебхуки. Для local smoke в
`saleor/`:

- **`common.env`**: `HTTP_IP_FILTER_ENABLED=False` — иначе Saleor отвергает
  установку App с manifest на private IP (`host.docker.internal` → 192.168.65.254)
  с ошибкой `Failed to install app. Error: 192.168.65.254`.
  ⚠️ Это отключает SSRF-защиту. **Только local. В prod — `True` + public HTTPS URL.**
- **`docker-compose.override.yml`**: `ALLOWED_HOSTS` содержит `host.docker.internal`
  — иначе middleware фетчит JWKS с `http://host.docker.internal:8000/.well-known/jwks.json`
  и Django отвечает `400 DisallowedHost`.

После правки — пересоздать (env_file читается только при создании):
```bash
cd saleor && docker compose up -d --force-recreate api worker
```

## Шаги

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
    appName:"Justix Odoo Sync (Smoke)"
    manifestUrl:"http://host.docker.internal:8080/api/manifest"
    activateAfterInstallation:true
    permissions:[MANAGE_ORDERS,MANAGE_PRODUCTS,MANAGE_USERS,MANAGE_PRODUCT_TYPES_AND_ATTRIBUTES,MANAGE_CHANNELS]
  }){ appInstallation{ id status } errors{ field message permissions } }
}
```
Header: `Authorization: Bearer <admin_token>`. Опрашивать `appsInstallations` до
`status=SUCCESS` (или исчезновения из списка). Если App с таким именем уже есть —
сначала `appDelete`.

После установки Saleor:
1. GET `/api/manifest` (200),
2. POST `/api/register` → middleware кладёт токен в Redis под
   `saleor_bridge:apl:<saleor_api_url>` (НЕ `app:<domain>`),
3. создаёт 6 webhooks из манифеста.

Проверка:
```bash
docker compose exec redis redis-cli KEYS "saleor_bridge:apl:*"
```

### 4. Trigger CUSTOMER_CREATED
```graphql
mutation { customerCreate(input:{
  email:"smoke-test-<ts>@example.com" firstName:"Smoke" lastName:"Test"
}){ user{ id email } errors{ message } } }
```

### 5. Верификация (~6с спустя)

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
`customerUpdate` (меняем `note` чтобы Saleor реально послал CUSTOMER_UPDATED) →
в Odoo НЕ появляется дубль (1 partner), `last_sync_in` свежее.

### 7. Cleanup
`appDelete` для "Justix Odoo Sync (Smoke)". `smoke_test.py` делает это сам (без
`--keep-app`). Smoke-test partner в Odoo оставляем как доказательство.

## Подводные камни (проверено)

| Симптом | Причина | Fix |
|---|---|---|
| `restart` не подхватил env | `docker compose restart` не перечитывает `.env`/`env_file` | `docker compose up -d <svc>` |
| `Failed to install app. Error: 192.168.65.254` | Saleor SSRF IP filter блокирует private IP | `HTTP_IP_FILTER_ENABLED=False` (local) |
| webhook 401 `jwks fetch failed: All connection attempts failed` | Saleor анонсит `localhost:8000`, недостижим из контейнера | middleware тянет JWKS с `BRIDGE_SALEOR_API_URL` (host.docker.internal) |
| webhook 401 `400 DisallowedHost` на JWKS | `host.docker.internal` не в `ALLOWED_HOSTS` | добавить в `saleor/docker-compose.override.yml` |
| webhook 401 `bad_signature` | Saleor подписывает RFC 7797 `b64:false`; middleware верифай ждал `b64:true` | fix в `signature.py` (поддержка b64:false) |
| odoo shell `${...}` не подставлен | shell с `-c /etc/odoo/odoo.conf` (там сырой `${}`) | использовать `/tmp/odoo.conf` (entrypoint подставляет env) |

## Prod (Phase 4) — чем отличается

- Public HTTPS URL (ngrok/Cloudflare/реальный домен) вместо `host.docker.internal`.
- `HTTP_IP_FILTER_ENABLED=True`, реальный домен в `ALLOWED_HOSTS`.
- Saleor `PUBLIC_URL` = публичный домен → `saleor-api-url` в вебхуках корректный,
  отдельный JWKS-override в middleware не нужен.
