# ADR-0019: Order status mapping Odoo → Saleor

## Status
Accepted (2026-05-23) — Phase 3.4

## Context

Phase 3.1 синкает заказы Saleor → Odoo (created/paid/cancelled). Обратное
направление (статус заказа Odoo → витрина) отсутствовало: покупатель не видел
«отправлен»/«отменён». Phase 3.4 закрывает Odoo → Saleor для жизненного цикла
заказа: confirm, fulfillment (отгрузка), cancel, manual payment.

Saleor order state machine **строгая** — мутации валидны только из определённых
статусов (нельзя `orderConfirm` на уже подтверждённом). Поэтому перед каждой
мутацией обязателен idempotency-pre-check текущего статуса (см. подводные камни).

## Decision

Триггер — Odoo `base.automation` `on_state_set` на `sale.order.state` и
`stock.picking.state` (точно ловит переход state-machine, без шума). Subject
события — модель + odoo_id; worker **перечитывает** текущее состояние из Odoo и
решает мутацию (как в ADR-0017: state, не event).

### sale.order.state

| Odoo state | Saleor статус (pre-check) | Мутация | Примечание |
|------------|---------------------------|---------|------------|
| `sale` (draft→sale) | UNCONFIRMED → | `orderConfirm(id)` | если уже не UNCONFIRMED → skip (no-op) |
| `cancel` | не CANCELED → | `orderCancel(id)` | FULFILLED → нельзя отменить, log + graceful skip |
| `done` (locked) | — | NO-OP | в Saleor нет аналога «locked»; покрыт fulfilled-статусом |

`orderConfirm` в этой версии Saleor — **без** `isPaid` (спека-черновик ошибалась);
просто `orderConfirm(id)`. Оплата уже синкнута Phase 3.1 (ORDER_FULLY_PAID).

### stock.picking.state

| Odoo state | Saleor статус (pre-check) | Мутация |
|------------|---------------------------|---------|
| `done` (отгрузка) | не FULFILLED → | `orderFulfill(order, input:{lines, notifyCustomer, allowStockToBeExceeded:false, trackingNumber})` |
| `cancel` (reverse) | — | NO-OP в MVP (fulfillmentCancel — Phase 4) |

`trackingNumber` (`carrier_tracking_ref`) передаётся **внутри** `OrderFulfillInput`
(отдельная tracking-мутация не нужна). `None` допустим.

Маппинг строк fulfillment: Odoo `stock.move.line.product_id.default_code` (SKU) →
Saleor `OrderLine` по `productSku` → `orderLineId` + `stocks:[{quantity, warehouse}]`.
Warehouse — тот же Saleor warehouse, что в ADR-0015 (binding `stock.warehouse`).

### account.move payment_state

| Odoo payment_state | Мутация |
|--------------------|---------|
| → `paid` (manual в Odoo) | `orderMarkAsPaid(id)` если `paymentStatus != FULLY_CHARGED` |

🚩 Почти все оплаты уже синкнуты Phase 3.1 (клиент платит на витрине). Phase 3.4
покрывает **manual payment из backoffice** — редкий case. Idempotency-check
обязателен (обычно no-op).

## Consequences

**Pros:** покупатель видит реальный статус (confirmed/fulfilled/cancelled/tracking);
один источник истины по операциям — Odoo backoffice.

**Cons:** строгая Saleor state-machine требует pre-check перед каждой мутацией
(+1 query). Partial fulfillment не покрыт (ADR-0021). Reverse-эхо требует
skip-guard (ADR-0020).
