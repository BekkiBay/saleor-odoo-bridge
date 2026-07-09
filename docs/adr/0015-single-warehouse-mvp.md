# ADR-0015: Single-warehouse MVP (1 Odoo warehouse → 1 Saleor warehouse)

## Status
Accepted (2026-05-23) — Phase 3.3

## Context

Odoo разделяет остатки по `stock.location` внутри `stock.warehouse`. Один товар
может иметь несколько `stock.quant` (разные локации, lot/serial). Saleor хранит
остаток как `Stock(variant, warehouse, quantity)` — одно число на пару
(variant, warehouse).

Полноценный multi-warehouse mapping (несколько складов Odoo → несколько Saleor
warehouses + shipping zones + channel allocation) — это значительный объём:
маппинг локаций, выбор warehouse per shipping zone, split остатков. Для текущего
каталога (30 SKU, один физический склад) это переинженеринг.

## Decision

**Один Odoo `stock.warehouse` ↔ один Saleor `Warehouse`.**

1. Middleware агрегирует **все** internal-quant'ы товара в одно число
   (`sum(quantity)` по `location_id.usage='internal'`), без разбивки по локациям.
2. Saleor-сторона: переиспользуем **уже существующий** Saleor `Warehouse` (тот,
   что Saleor создаёт при инициализации и который привязан к shipping zone
   `default-channel`). Маппинг Odoo warehouse → этот Saleor warehouse хранится в
   `saleor.binding` с `model_name='stock.warehouse'` (см. ADR-0007, переиспользуем
   инфраструктуру биндингов вместо новой модели).
3. Если в Saleor нет ни одного warehouse — создаём новый со slug
   `{odoo_code}-{odoo_id}` (гарантия уникальности, см. подводные камни 3.3). Но
   в нормальном flow MVP мы привязываемся к существующему, чтобы остаток сразу
   попадал в `quantityAvailable(channel)` без ручной привязки warehouse↔channel.

## Alternatives considered

- **Создавать отдельный Saleor warehouse под Odoo-склад.** Отброшено для MVP:
  новый warehouse не привязан к shipping zone канала → `quantityAvailable` в
  канале = 0, товар «нет в наличии» несмотря на остаток. Потребовало бы
  warehouse↔shippingZone↔channel wiring. Переиспользование дефолтного warehouse
  убирает эту проблему.
- **Multi-warehouse сразу.** Отброшено: нет бизнес-потребности (один склад),
  раздуло бы Phase 3.3. Отложено в Phase 4.

## Consequences

**Pros:** простой маппинг, остаток сразу виден в канале, ноль нового Odoo-кода
(переиспользуем `saleor.binding`).

**Cons:** при появлении второго склада в Odoo остатки схлопнутся в один Saleor
warehouse (потеря разбивки). Закрывается в Phase 4 (multi-warehouse mapping).
`fetch_aggregated_stock` уже возвращает `list[StockLevel]` (per warehouse), так
что расширение до multi-warehouse — аддитивное.
