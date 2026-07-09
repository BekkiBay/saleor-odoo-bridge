# ADR-0009: Refunds отложены на Phase 4 (не Phase 3)

## Status
Accepted (2026-05-21)

## Context

Phase 3 MVP scope (см. [research doc §9](../phase-3-integration-research.md)):

- 3.1 Saleor → Odoo orders + customers
- 3.2 Odoo → Saleor catalog
- 3.3 Stock sync
- 3.4 Order status Odoo → Saleor
- 3.5 Variants + attributes

Phase 3.6 (refunds) изначально планировался — отменён по решению заказчика. Reasoning: маркетплейс одежды в UZ, return rate низкий первые месяцы; полная schema refund (partial refund + stock return + invoice reversal) добавляет 12+ часов и сложные edge cases (chargebacks, exchange vs refund), которые лучше делать когда есть реальные данные о return patterns.

## Decision

**В Phase 3 refunds не реализуются.**

Конкретно:
- Webhook `ORDER_REFUNDED` / `ORDER_FULLY_REFUNDED` — **не подписываемся** в манифесте.
- Mapping для `account.move` (`out_refund`) / `account.payment` (outbound) — не пишем.
- Reverse stock picking — не пишем.

`ORDER_CANCELLED` (full cancel before fulfillment) — **обрабатываем** (см. ADR-0005), это не refund в финансовом смысле — `_action_cancel()` на sale.order, отпускает reserved stock, не трогает money.

**Schema requirement:** дизайн `saleor.binding` и mapping table должен **допускать добавление refunds без breaking changes**.

Конкретно:
- `saleor.binding.model_name` уже generic — можно добавить `account.payment`, `account.move`, `stock.return.picking` records.
- `saleor.binding.saleor_id` хранит base64 ID — `TransactionItem.id` поместится туда же без изменения схемы.
- `sync_state` Selection включает `synced`, `failed`, `diverged` — добавится `refunded` без миграции (Selection extension в Odoo идемпотентна).

## Alternatives considered

1. **Реализовать "minimal refund" — только full refund.** **Отброшено:** партиал в реальных кейсах = 80% возвратов. Half-feature хуже чем no feature.

2. **Implement стoral schema для refunds, но без logic.** Заглушки + DB schema. **Отброшено:** YAGNI. Schema всё равно изменится когда возьмёмся за реальную логику.

## Consequences

**Pros:**
- -12 часов из Phase 3 → быстрее доставка MVP.
- Меньше edge cases на тестировании Phase 3.5.
- Реальные return patterns соберутся за 2-3 месяца — лучшее design refund flow.

**Cons:**
- Заказчику нужен manual workflow для refunds в Phase 3 период:
  - Refund в платёжке вручную (UZcard/Click/Payme dashboard).
  - Cancel order в Saleor Dashboard.
  - Reverse stock в Odoo вручную (`Inventory → Adjustments`).
- Эту операционку надо задокументировать (runbook).

**Mitigation:**
- В `docs/runbooks/manual-refund.md` (создаётся в Phase 3.1) — пошаговая инструкция для оператора.
- В Phase 4 — `saleor_sync.refund` model + automated flow. Бэк-фил исторических refunds — отдельным cron, по `ORDER_REFUNDED` событиям из Saleor history (Saleor хранит).
