# ADR-0011: Secret в URL query для outbound webhooks Odoo → middleware

## Status
Accepted (2026-05-23) — Phase 3.2

## Context

Reverse flow (Phase 3.2): изменение `product.template` / `product.category` в Odoo
должно долететь до middleware (`POST /api/odoo-events`), который положит job в arq
и запушит в Saleor.

Триггер на стороне Odoo — `base.automation` (`on_create_or_write`) → серверный
action. Нужно аутентифицировать вызов middleware, чтобы кто угодно не дёргал
`/api/odoo-events`.

Варианты доставки секрета:

1. **HMAC-подпись тела в заголовке** (как Saleor подписывает свои webhooks, см.
   `saleor/signature.py`). Самый стойкий: тело нельзя подменить, replay ограничен
   по времени.
2. **Bearer-токен в заголовке `Authorization`.**
3. **Секрет в query-параметре `?secret=...`.**

Ограничение Odoo: нативный webhook server-action (`state='webhook'`) **не умеет**
кастомные заголовки — только URL + список полей. Чтобы получить и outbox-запись, и
guard от эхо-петли, мы пишем серверный action `state='code'` (Python), который сам
делает `POST`. В коде заголовки технически доступны, но мы сознательно остаёмся на
query-секрете ради простоты и единообразия с тем, на что Odoo способен из коробки.

## Decision

**Секрет передаётся в query-параметре:**

```
POST {saleor_sync.middleware_url}/api/odoo-events?secret={saleor_sync.webhook_secret}
Body: {"odoo_model": "...", "odoo_id": N, "action": "create|write|unlink"}
```

- `webhook_secret` хранится в `ir.config_parameter` (`saleor_sync.webhook_secret`),
  значение из env `BRIDGE_ODOO_WEBHOOK_SECRET` (тот же секрет на стороне middleware
  через `BRIDGE_ODOO_WEBHOOK_SECRET`).
- Middleware сравнивает константно-временно (`hmac.compare_digest`), на mismatch → 401.
- Связь Odoo→middleware идёт по внутренней docker-сети (`http://middleware:8080`),
  наружу не выходит. Query-секрет в логах reverse-proxy — приемлемый риск для
  internal hop; для prod HTTPS-туннель закрывает перехват.

## Alternatives considered

- **HMAC (вариант 1).** Стойче, но сложнее: нужно делить ключ, сериализовать тело
  детерминированно, проверять timestamp. Отложено в Phase 4 (extended action с
  подписью). Для internal hop за reverse-proxy выгода мала.
- **Bearer header (вариант 2).** Эквивалентно по стойкости query-секрету, но требует
  явного добавления заголовка; преимущества над query нет, раз hop внутренний.

## Consequences

**Pros:** минимум кода, отлаживается `curl`'ом, секрет ротируется через один
config-parameter + env.

**Cons:** секрет виден в URL (access-логи прокси). Нет защиты от replay и от подмены
тела. Допустимо, т.к. вызов internal и тело — лишь `(model, id, action)`; middleware
всё равно перечитывает актуальную запись из Odoo по `id` перед push (источник правды
— Odoo, ADR-0006), так что подделанное тело не приводит к записи поддельных данных.

**Миграция (Phase 4):** заменить `?secret=` на HMAC-заголовок + timestamp; endpoint
будет принимать оба в переходный период.
