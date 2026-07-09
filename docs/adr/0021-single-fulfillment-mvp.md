# ADR-0021: Single full fulfillment per order (MVP)

## Status
Accepted (2026-05-23) — Phase 3.4

## Context

Odoo допускает несколько `stock.picking` на один `sale.order` (частичные
отгрузки, backorder, многокоробочная доставка). Saleor поддерживает несколько
`Fulfillment` на заказ. Полный partial-fulfillment маппинг (трекинг какая строка
сколько отгружена, какой picking → какой fulfillment, дозаказы) — значительный
объём и состояние.

Для текущего MVP-маркетплейса заказ отгружается одним picking'ом целиком.

## Decision

**Один полный fulfillment на заказ.**

- На `picking.state = done` пушим `orderFulfill` по строкам этого picking'а
  (`move_line_ids` → SKU → Saleor `OrderLine`), количество = `quantityToFulfill`
  (то, что ещё не отгружено).
- Если заказ уже `FULFILLED` целиком → skip (idempotency).
- Если отгружена часть → Saleor покажет `PARTIALLY_FULFILLED` (поведение
  корректно, но мы НЕ оркеструем несколько picking'ов осознанно — это побочный
  результат, не поддерживаемый сценарий).
- `fulfillmentCancel` (reverse отгрузки) — **NO-OP** в MVP.

## Alternatives considered

- **Полный partial-fulfillment с маппингом picking↔fulfillment.** Отброшено в
  3.4: требует хранить соответствие picking→fulfillment id, обрабатывать
  backorder/дозаказ. Отложено в Phase 4.
- **Запрещать частичную отгрузку в Odoo.** Отброшено: нельзя ломать backoffice-flow
  оператора ради ограничения витрины.

## Consequences

**Pros:** простой и предсказуемый fulfillment, покрывает основной кейс
(отгрузил — клиент увидел «Fulfilled» + tracking).

**Cons:** многократные частичные отгрузки одного заказа в MVP не оркестрируются
(каждый `done`-picking шлёт свой `orderFulfill` по оставшимся строкам; при
сложных сценариях возможны несогласованности). Reverse (`fulfillmentCancel`),
multi-package, backorders — Phase 4. Документировано в out-of-scope Phase 3.4.
