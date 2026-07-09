# ADR-0022: Customer notification policy на order-мутациях

## Status
Accepted (2026-05-23) — Phase 3.4

## Context

При синке статуса заказа Odoo → Saleor нужно решить, слать ли покупателю email.
Не каждое изменение интересно клиенту: подтверждение оплаты — техническая
транзакция, а вот «заказ отправлен» с трек-номером — важное событие.

Реальность схемы Saleor (этой версии) ограничивает контроль:
- `orderFulfill(input: OrderFulfillInput)` — **есть** `notifyCustomer: Boolean`.
- `orderConfirm(id)`, `orderCancel(id)`, `orderMarkAsPaid(id)` — параметра notify
  **нет**; рассылку этих событий определяют настройки Saleor (Shop/Channel).

## Decision

**Контролируем notify там, где Saleor это позволяет — на `orderFulfill`:**

| Мутация | notify | Как реализовано |
|---------|--------|-----------------|
| `orderFulfill` | **True** | `OrderFulfillInput.notifyCustomer = True` (клиенту важно «отправлено» + трек) |
| `orderConfirm` | n/a | параметра нет; письмо confirm управляется настройками Saleor — мы доп. не шлём |
| `orderCancel` | n/a | параметра нет; уведомление об отмене — по настройкам Saleor |
| `orderMarkAsPaid` | n/a (False по смыслу) | параметра нет; тихая backoffice-операция |

`notify_customer` пробрасывается параметром в usecase/adapter (default `True` для
fulfill) — конфигурируемо на будущее, но в MVP фактически влияет только на
`orderFulfill`.

## Alternatives considered

- **Слать всё (notify везде True).** Отброшено: на confirm/markPaid у Saleor нет
  параметра, а спам клиенту техническими письмами — плохой UX (где есть контроль —
  на fulfill — оставляем True).
- **Не слать ничего (notify=False на fulfill).** Отброшено: «заказ отправлен» —
  ключевое письмо для клиента (снижает «где мой заказ?» обращения в support).

## Consequences

**Pros:** клиент получает значимое уведомление об отгрузке с трек-номером;
техно-транзакции не контролируются нами вручную (Saleor сам по настройкам).

**Cons:** confirm/cancel-уведомления вне нашего прямого контроля (зависят от
настроек Saleor) — если потребуется тонкая политика, нужен Saleor-config (Phase 4).
