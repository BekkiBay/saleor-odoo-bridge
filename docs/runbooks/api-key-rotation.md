# Runbook — Odoo API key rotation (middleware)

Middleware ходит в Odoo по JSON-2 REST API (`/json/2/...`) с
`Authorization: bearer <BRIDGE_ODOO_API_KEY>`. Ключ привязан к пользователю
`admin@marketplace.local` (uid 2), **scope = NULL** (global — нужно для JSON-2),
TTL **3 месяца**.

## Когда ротировать

- За ~1 неделю до истечения (см. таблицу ниже).
- При компрометации `.env` / утечке ключа.
- При смене admin-пользователя.

| Создан | Истекает | Действие |
|---|---|---|
| 2026-05-23 | **2026-08-23** | ротировать до 2026-08-16 |

> Обновляй эту строку при каждой ротации.

## Ротация

```bash
cd odoo-saleor-integration
.venv/bin/python scripts/generate_api_key.py        # генерит новый, пишет в .env
docker compose up -d middleware middleware-worker    # подхватить новый ключ (НЕ restart)
curl http://localhost:8080/health                    # {"odoo":"ok"}
```

Скрипт:
1. Удаляет старые ключи с именем `saleor-bridge-smoke` у admin-юзера (идемпотентно).
2. Генерит новый: `env['res.users.apikeys'].with_user(admin)._generate(None, 'saleor-bridge-smoke', now+3мес)`.
   - `_generate` привязывает ключ к `self.env.user` → используется `with_user(admin)`.
   - scope `None` (НЕ `'rpc'`) — JSON-2 API требует global-scope ключ.
3. Печатает `BRIDGE_ODOO_API_KEY=<key>` и переписывает строку в `.env`.

Проверка в БД:
```bash
docker exec odoo-db psql -U admin -d marketplace -tA -c \
  "SELECT name,user_id,scope,expiration_date FROM res_users_apikeys WHERE name='saleor-bridge-smoke';"
# saleor-bridge-smoke|2||<exp>     (scope пустой = NULL)
```

## Гочи

- **odoo shell не интерактивен в скрипте** — `generate_api_key.py` пайпит код в
  `docker compose exec -T odoo odoo shell -d marketplace --no-http -c /tmp/odoo.conf`.
  Конфиг именно `/tmp/odoo.conf` (entrypoint подставил туда env; в
  `/etc/odoo/odoo.conf` остаются сырые `${...}`).
- **После записи в `.env`** middleware/worker нужно **пересоздать** (`up -d`),
  `restart` не перечитывает переменные окружения.
- **Ключ виден один раз** — после генерации только хэш в БД. Потерял → генери заново.
