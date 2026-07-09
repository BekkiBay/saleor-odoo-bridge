# ADR-0020: Reverse-echo prevention via skip-guard context

## Status
Accepted (2026-05-23) — Phase 3.4. Расширяет механизм из Phase 3.2 (`saleor_sync_skip`).

## Context

Phase 3.1 меняет `sale.order` в Odoo по Saleor-вебхуку (ORDER_FULLY_PAID →
`action_confirm`). Phase 3.4 ловит изменение `sale.order.state` и пушит обратно в
Saleor. Без защиты — **бесконечная петля**:

1. Saleor ORDER_FULLY_PAID → Phase 3.1 `action_confirm` в Odoo.
2. Odoo state draft→sale → Phase 3.4 automation → `orderConfirm` в Saleor.
3. Saleor ORDER_CONFIRMED → (потенциально) снова в Odoo → …

## Decision

Переиспользуем существующий context-флаг **`saleor_sync_skip`** (его уже уважают
все outbound-диспетчеры: `_emit`/`_dispatch*` проверяют
`records.env.context.get('saleor_sync_skip')`).

**Phase 3.1 при любом write в Odoo из Saleor-события передаёт
`context={'saleor_sync_skip': True}`** в JSON-2 вызов:

```python
await odoo.call("sale.order", "action_confirm", ids=[order_id],
                context={"saleor_sync_skip": True})
```

Server action новой automation видит флаг в `env.context` → `pass` (не эмитит
событие). Эхо разорвано на первом же звене.

**Проверено:** Odoo 19 JSON-2 (`POST /json/2/{model}/{method}`) пробрасывает ключ
`context` в `env.context` (probe через `default_get(default_note=...)`).

Применяем к Phase 3.1 операциям: `create` (draft), `action_confirm`,
`action_cancel`.

## Alternatives considered

- **Дедуп на стороне middleware** (помнить «этот state-change я сам вызвал»).
  Отброшено: stateful, гонки, сложнее context-флага, который уже встроен.
- **Отдельный technical-user/marker-поле** на sale.order. Отброшено: лишняя
  схема; context чист и транзакционен (живёт только в рамках вызова).

## Consequences

**Pros:** ноль новой инфраструктуры (флаг уже есть), транзакционно-локально,
не оставляет следов. S4 hardening подтверждает отсутствие эха.

**Cons:** зависит от проброса context через JSON-2 (проверено для Odoo 19). Если
кто-то поменяет state в Odoo **вручную** (не из Saleor) — флага нет, push
произойдёт (это и есть желаемое поведение). Эхо-риск только на Saleor-инициированных
изменениях, где флаг ставится.
