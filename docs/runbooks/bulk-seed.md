# Runbook — Bulk seed каталога Odoo → Saleor (Phase 3.2)

Первичная выгрузка каталога (18 категорий + 30 продуктов) из Odoo в Saleor и
последующая инкрементальная синка по webhook'ам. См. ADR-0011..0014.

## Архитектура (reverse flow)

```
Odoo product.template/category  ──base.automation──▶ ir.actions.server (code)
   │ _saleor_dispatch() пишет saleor.outbox + POST
   ▼
POST {middleware}/api/odoo-events?secret=…   (ADR-0011)
   │ validate secret → enqueue arq (defer ~3s, dedup по model+id) → 200
   ▼
arq worker: sync_odoo_record_to_saleor
   fetch из Odoo (JSON-2) → resolve binding → Saleor mutation → upsert saleor.binding
```

Bulk seed обходит webhook flow и пушит весь каталог сам (ADR-0013).

## Предусловия

1. **Оба стека подняты:**
   ```bash
   cd odoo-saleor-integration && docker compose up -d
   cd ../saleor && docker compose up -d
   ```
2. **Odoo настроен** (saleor_sync v0.2 установлен, каталог импортирован):
   ```bash
   .venv/bin/python scripts/odoo_setup.py        # 30 products + 18 categories
   ```
3. **Odoo API key** в `.env` (`BRIDGE_ODOO_API_KEY`) — `scripts/generate_api_key.py`.
4. **Webhook secret** одинаковый у обеих сторон:
   ```
   BRIDGE_ODOO_WEBHOOK_SECRET=<32+ случайных символа>
   ```
   После правки `.env` — пересоздать (НЕ `restart`):
   ```bash
   docker compose up -d odoo middleware middleware-worker
   ```
   Если saleor_sync уже стоял — обнови, чтобы post_init записал config-param:
   ```bash
   docker compose exec odoo odoo -c /tmp/odoo.conf -d marketplace -u saleor_sync --stop-after-init
   docker compose restart odoo
   ```
5. **Bridge Saleor App установлен** (даёт middleware право писать в Saleor):
   ```bash
   # public URL должен быть достижим из Saleor-контейнера:
   #   BRIDGE_MIDDLEWARE_PUBLIC_URL=http://host.docker.internal:8080
   .venv/bin/python scripts/install_bridge_app.py
   docker compose exec redis redis-cli KEYS 'saleor_bridge:apl:*'   # должен быть ключ
   ```

## Seed

```bash
# 1. План (read-only, ничего не меняет):
docker compose exec middleware python -m saleor_bridge.cli.bulk_seed bulk-seed --dry-run

# 2. (опционально, DESTRUCTIVE) очистить существующий Saleor-каталог:
docker compose exec middleware python -m saleor_bridge.cli.bulk_seed wipe --yes

# 3. Реальный прогон (идемпотентно):
docker compose exec middleware python -m saleor_bridge.cli.bulk_seed bulk-seed
```

Ожидаемый итог: 1 ProductType + 18 categories + 30 products, все опубликованы в
`default-channel` с ценой UZS. В Odoo `saleor.binding` — 49 записей `state='synced'`.

Повторный `bulk-seed` НЕ создаёт дублей — обновляет существующие (lookup по
`saleor.binding.odoo_id`).

## Проверка (Saleor GraphQL, через bridge-app токен)

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

## Инкрементальная синка (после seed)

Изменишь имя/цену товара в Odoo → `base.automation` → outbox → middleware → Saleor
за ~5 сек. Проверка: открой Saleor Dashboard либо повтори GraphQL-запрос выше.

## Troubleshooting

| Симптом | Причина | Что делать |
|---|---|---|
| `NoSaleorToken` в CLI | bridge-app не установлен / токен протух | `python scripts/install_bridge_app.py`, проверь APL ключ |
| `PermissionDenied: MANAGE_PRODUCTS` | App без прав (старый/удалённый) | переустанови app, см. п.5 предусловий |
| `channel 'default-channel' не найден` | App без MANAGE_CHANNELS | переустанови app (PERMISSIONS включают MANAGE_CHANNELS) |
| 401 от `/api/odoo-events` | секрет не совпал | сверь `saleor_sync.webhook_secret` (Odoo) и `BRIDGE_ODOO_WEBHOOK_SECRET` (middleware) |
| webhook не приходит | автоматизация выключена / Odoo не видит middleware | проверь base.automation активна; `BRIDGE_MIDDLEWARE_INTERNAL_URL=http://middleware:8080` |
| seed создал дубли | binding потёрт | дубли удали через `wipe`, повтори seed |

## Force-resync одного товара

```bash
# через Odoo shell — тронуть write_date, что запустит automation:
docker compose exec odoo odoo shell -c /tmp/odoo.conf -d marketplace <<'PY'
env['product.template'].browse(7).write({'name': env['product.template'].browse(7).name})
env.cr.commit()
PY
```
