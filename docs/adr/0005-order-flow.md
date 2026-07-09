# ADR-0005: Order flow — ORDER_CREATED → draft, ORDER_PAID → confirm

## Status
Accepted (2026-05-21)

## Context

Saleor order lifecycle: `Checkout` → `ORDER_CREATED` (placed) → `ORDER_CONFIRMED` (admin) → `ORDER_PAID` / `ORDER_FULLY_PAID` → `ORDER_FULFILLED`.

Odoo `sale.order.state`: `draft` → `sent` → `sale` → `cancel`. (В Odoo 19 убрали `done` — теперь `state='sale' AND locked=True`.) Переход `draft → sale` через `action_confirm()` — резервирует склад, создаёт `stock.picking`, делает SO видимым в operational dashboard.

Решаем когда именно создавать `sale.order` и когда подтверждать.

## Decision

**Двухфазный mapping:**

1. **`ORDER_CREATED` → создать `sale.order` в state `draft`.**
   - `partner_id`, `partner_invoice_id`, `partner_shipping_id` — resolved через `res.partner` (создаются если нет).
   - `order_line` — заполняется со всеми SKU.
   - `client_order_ref = saleor_order_number` для дедупа.
   - НЕ вызываем `action_confirm()` — заказ висит в дашборде sales-операторов как unconfirmed quote.

2. **`ORDER_PAID` / `ORDER_FULLY_PAID` → вызвать `action_confirm()` + auto-invoice.**
   - Идемпотентно: если `state == 'sale'` — no-op.
   - После confirm — `_create_invoices()` → `action_post()` → `account.payment.register`.

3. **`ORDER_CANCELLED` → вызвать `_action_cancel()` в Odoo.**

4. **`ORDER_UPDATED`** (между created и paid) — обновляем lines на draft SO. После confirm — игнорируем (lines зафиксированы).

## Alternatives considered

1. **`ORDER_PAID` → create+confirm одновременно.** Operator не видит unpaid orders в Odoo, только оплаченные. **Отброшено:** теряем visibility unconfirmed/expired orders для аналитики ("сколько заказов недоплачено за день").

2. **`ORDER_CREATED` → create + immediate confirm.** Sale-order сразу резервирует склад, даже до оплаты. **Отброшено:** если клиент бросил оплату → reserved stock залипает до cancel webhook'а. Riskier для inventory accuracy.

3. **`ORDER_CONFIRMED` (admin confirmation in Saleor Dashboard) → create в Odoo.** **Отброшено:** заказчик не использует ручную модерацию заказов в Saleor — все orders auto-confirmed.

## Consequences

**Pros:**
- Operator видит весь flow от placement до payment.
- Stock reservation только после реальной оплаты — нет orphan-reservations.
- Sale.order draft = audit trail для "клиент пытался".

**Cons:**
- Два webhook'а вместо одного — два места где может упасть sync.
- Draft sale.order'ы накапливаются для cancelled/expired — нужен cron-clean (отдельно, Phase 4).

**Mitigation:**
- Idempotency: оба webhook'а делают upsert по `client_order_ref`. Дубликаты не создают сущности.
- При `ORDER_PAID` без предшествующего `ORDER_CREATED` (race condition или потеря первого) — создаём SO и сразу подтверждаем.

См. также: [ADR-0009](0009-refunds-deferred.md) (cancel/refund flow отложен).
