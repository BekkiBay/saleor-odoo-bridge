# ADR-0014: Stock и warehouses вне scope Phase 3.2 (in scope 3.3)

## Status
Accepted (2026-05-23) — Phase 3.2

## Context

Saleor допускает создание `Product` + `ProductVariant` **без** stock-записей
(`Stock` / `Warehouse`). Вариант просто не имеет остатка; при `allowUnpaidOrders`
и без `trackInventory` он покупаем. Полный stock-sync (остатки, резервирование,
reconcile-cron, safety buffer) — это ADR-0010 и Phase 3.3.

## Decision

В Phase 3.2 продукты создаются **без stock entries**:

- `ProductVariant.trackInventory = false` — Saleor не блокирует покупку по остатку.
- Никаких `stockUpdate` / `Warehouse` мутаций.
- `quantityAvailable` в Saleor для этих вариантов будет 0/непоказателен — это ок для
  3.2 (цель — товар виден и заказуем в storefront для E2E).

Остатки появятся в Phase 3.3 (см. ADR-0010): отдельный flow Odoo `stock.quant` →
Saleor `Stock`, с safety buffer и reconcile-cron.

## Alternatives considered

- **Создавать stock=0 явно.** Отброшено: `trackInventory=false` проще и не делает
  товар «нет в наличии».
- **Тянуть stock сразу.** Отброшено: это Phase 3.3, требует warehouse-маппинга и
  reconcile-логики; раздуло бы 3.2.

## Consequences

**Pros:** проще, меньше мутаций, товар сразу заказуем для E2E-демо.

**Cons:** до Phase 3.3 в Saleor нет реальных остатков — overselling не контролируется
на стороне Saleor (Odoo остаётся источником истины по остаткам). Известный временный
зазор, закрывается в 3.3.
