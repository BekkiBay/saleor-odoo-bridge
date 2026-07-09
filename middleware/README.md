# Saleor Bridge — Middleware

Phase 3.1. FastAPI-сервис + arq worker между Saleor 3.23 и Odoo 19. Синк customers + orders Saleor → Odoo.

См. [`../docs/decisions.md`](../docs/decisions.md) — архитектурные решения. См. [`../docs/phase-3-integration-research.md`](../docs/phase-3-integration-research.md) — research.

## Что умеет (Phase 3.1)

**Endpoints (FastAPI):**
- `GET /health` — статус + проверка Redis/Odoo.
- `GET /api/manifest` — App manifest (6 webhook subscriptions).
- `POST /api/register` — token exchange.
- `POST /api/webhooks/{event}` — 6 webhook receiver'ов: JWS verify → idempotency (Redis SET NX 24h) → enqueue arq → 200.

**Worker (arq):**
- `CUSTOMER_CREATED` / `CUSTOMER_UPDATED` → upsert `res.partner` (по email, + child addresses invoice/delivery).
- `ORDER_CREATED` → `sale.order` draft (+ ensure customer, resolve product по SKU).
- `ORDER_CONFIRMED` → noop (ждём PAID, ADR-0005).
- `ORDER_FULLY_PAID` → `action_confirm` → state `sale`.
- `ORDER_CANCELLED` → `action_cancel` → state `cancel`.
- Retry: 3 попытки exponential backoff. После — Slack + email + `saleor.binding.sync_state='failed'` (ADR-0008).

**Архитектура (hexagonal / ports & adapters):**
```
adapters/saleor/  — payload → domain (Saleor-specific)
domain/           — чистые pydantic модели (platform-independent)
usecases/         — бизнес-логика (sync_customer, sync_order)
adapters/odoo/    — domain → JSON-2 calls (Odoo-specific)
```
Завтра Shopify → добавить `adapters/shopify/`, остальное не трогать.

## Архитектурная диаграмма

```
Saleor ──webhook──▶ FastAPI (/api/webhooks/{event})
                    JWS verify → idempotency → enqueue arq → 200
                                                      │
                                          Redis ◀─────┘
                                            │
                              arq worker ◀──┘
                              payload→domain→usecase
                                            │ JSON-2 (bearer apikey)
                                            ▼
                                          Odoo (res.partner, sale.order)
```

## Требования

- Python **3.11+** (если у тебя 3.9 — обнови или используй `uv python install 3.12`).
- Docker 24+ (для compose-режима).
- Публичный URL для Saleor webhooks (ngrok / Cloudflare Tunnel).

## Быстрый старт — через docker compose

Из корня `odoo-saleor-integration/`:

```bash
# 1. Все env vars (включая BRIDGE_*) лежат в корневом /.env.
#    Запусти ../../scripts/setup-env.sh — он сделает симлинк odoo-saleor-integration/.env -> ../.env
../../scripts/setup-env.sh

# 2. Поднять весь стек (db + odoo + redis + middleware)
docker compose up -d

# 3. Проверить
curl http://localhost:8080/health
curl http://localhost:8080/api/manifest
```

## Локальный dev (без Docker)

```bash
cd middleware
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"

# Env берётся из корневого /.env через симлинк odoo-saleor-integration/.env (см. ../../scripts/setup-env.sh).
# Для standalone dev можешь экспортить BRIDGE_* напрямую: `set -a; source ../.env; set +a`

# Redis нужен — поднимай отдельно: docker run -p 6379:6379 -d redis:7-alpine

uvicorn saleor_bridge.main:app --reload --port 8080
```

## Тесты

```bash
cd middleware
uv pip install -e ".[dev]"
pytest -v
```

Покрывают:
- `test_signature.py` — JWS verify happy path + 4 failure modes.
- `test_manifest.py` — substitution public URL, permissions, smoke webhook.

## ngrok setup (для приёма webhooks от Saleor)

Saleor должен ходить к нашему middleware через интернет. Локально — через ngrok.

```bash
brew install ngrok
ngrok config add-authtoken <твой токен с ngrok.com>
ngrok http 8080
```

Скопируй HTTPS URL вида `https://abc123.ngrok-free.app` в `.env`:

```
BRIDGE_MIDDLEWARE_PUBLIC_URL=https://abc123.ngrok-free.app
```

**Important:** на free tier ngrok URL **меняется при каждом перезапуске**. После рестарта:
1. Обнови `BRIDGE_MIDDLEWARE_PUBLIC_URL` в `.env`.
2. `docker compose restart middleware`.
3. Перерегистрируй App в Saleor (`appInstall` с новым manifest URL).

**Альтернатива — Cloudflare Tunnel** (stable URL без paid tier):
- Регистрация на Cloudflare → Zero Trust → Tunnels.
- `brew install cloudflared`.
- `cloudflared tunnel create saleor-bridge`.
- Mapped DNS → routes на `localhost:8080`.

## Smoke test end-to-end

После того как ngrok запущен и middleware up:

1. **Проверь manifest доступен снаружи:**
   ```bash
   curl https://<ngrok-subdomain>.ngrok-free.app/api/manifest
   ```
   Должен вернуть JSON с `id`, `permissions`, `webhooks` (один на CUSTOMER_CREATED).

2. **Установи App в Saleor через GraphQL** (Saleor Dashboard → Apps → "Local apps" → "Add app from URL", или прямой mutation):
   ```graphql
   mutation {
     appInstall(input: {
       appName: "Justix Odoo Sync"
       manifestUrl: "https://<ngrok-subdomain>.ngrok-free.app/api/manifest"
       permissions: [MANAGE_ORDERS, MANAGE_PRODUCTS, MANAGE_USERS, MANAGE_PRODUCT_TYPES_AND_ATTRIBUTES, MANAGE_CHANNELS]
     }) {
       appInstallation { id status appName manifestUrl }
       appErrors { field message code }
     }
   }
   ```

3. **Saleor POST'нет на `/api/register`** — middleware сохранит token в Redis. В логах:
   ```
   {"event": "register_ok", "saleor_api_url": "...", "domain": "...", "token_len": 30}
   ```

4. **Создай тестового клиента** в Saleor Dashboard (Customers → New) или через GraphQL `customerCreate`.

5. **В логах middleware появится:**
   ```
   {"event": "webhook_received", "event": "CUSTOMER_CREATED", "signature_valid": true, "kid": "...", "took_ms": 23}
   ```

Если signature_valid=false — проверь, что middleware ходит за JWKS на правильный URL (`{saleor}/.well-known/jwks.json`).

## Phase 3.1 — local E2E test (без ngrok)

Webhook signature тестируется unit-тестами. Бизнес-логику (worker → Odoo) можно прогнать **без Saleor/ngrok**, enqueue'я job напрямую в arq.

**Сначала: Odoo API key** (JSON-2 требует bearer). Сгенерировать для admin-пользователя (uid 2, не superuser — у superuser `active=false`, JSON-2 его отвергнет; нужен **global scope = NULL**, не 'rpc'):

```bash
printf "env['res.users.apikeys'].with_user(2)._generate(None,'saleor-bridge','2026-12-31 23:59:59')\nenv.cr.commit()" \
  | docker compose exec -T odoo odoo shell -c /tmp/odoo.conf -d marketplace --no-http
# скопировать ключ → .env BRIDGE_ODOO_API_KEY → docker compose up -d middleware middleware-worker
```

В проде ключ создаётся через UI: Preferences → Account Security → New API Key.

**Прогон customer + order:**

```bash
docker compose exec -T middleware python -c "
import asyncio
from saleor_bridge.queue.pool import make_arq_pool
from saleor_bridge.config import get_settings
cust={'event':{'user':{'id':'VXNlcjox','email':'a@example.com','firstName':'A','lastName':'B',
  'defaultBillingAddress':{'streetAddress1':'St 1','city':'Tashkent','country':{'code':'UZ'},'phone':'+998901112233'}}}}
order={'event':{'order':{'id':'T3JkZXI6MQ==','number':'1001','userEmail':'a@example.com',
  'lines':[{'productName':'X','productSku':'SKU-001','quantity':2,'unitPrice':{'gross':{'amount':'450000','currency':'UZS'}},'variant':{'sku':'SKU-001'}}],
  'total':{'gross':{'amount':'900000','currency':'UZS'}}}}}
async def m():
    p=await make_arq_pool(get_settings().redis_url)
    await p.enqueue_job('process_customer_created',cust); await asyncio.sleep(2)
    await p.enqueue_job('process_order_created',order); await asyncio.sleep(2)
    await p.enqueue_job('process_order_paid',order)
    await p.aclose()
asyncio.run(m())
"
docker compose logs -f middleware-worker   # смотреть customer_synced / order_created / order_confirmed
```

Проверить в Odoo: Contacts → новый partner; Sales → новый order (draft → sale после paid).

**Note:** email с `.test`/reserved TLD отвергается pydantic EmailStr — используй `example.com`.

## Troubleshooting

**`{"status": "ok", "redis": "fail", "odoo": "fail"}` на /health**
Middleware не достучался до Redis или Odoo. Из docker compose контейнера — `BRIDGE_REDIS_URL=redis://redis:6379/0` (имя сервиса), `BRIDGE_ODOO_URL=http://odoo:8069`. Из локального dev — `redis://localhost:6379/0` и `http://localhost:8069`.

**Saleor self-hosted не доступен из middleware-контейнера**
На macOS/Windows — `http://host.docker.internal:8000/graphql/`. На Linux — добавь `extra_hosts: ["host.docker.internal:host-gateway"]` в compose.

**JWKS endpoint не найден (404)**
Saleor 3.5+ выставляет на `{shop_url}/.well-known/jwks.json`. Если у вас reverse proxy перекрывает `/.well-known/*` — пропустить через proxy.

**`Saleor-Signature` header пустой**
Возможно у webhook'а включён legacy HMAC mode (`secretKey` задан). В Phase 3.0 поддерживаем только JWS. Создавай webhook без `secretKey`. См. ADR-0002.

**После рестарта ngrok URL поменялся**
Это норма на free tier. Update `.env` + `docker compose restart middleware` + перерегистрируй App в Saleor.
