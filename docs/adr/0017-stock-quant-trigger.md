# ADR-0017: Триггер стока = `stock.quant` write (поле `quantity`)

## Status
Accepted (2026-05-23) — Phase 3.3

## Context

Нужно ловить изменение остатка в Odoo и пушить в Saleor. Кандидаты:

- **`stock.move`** — событие движения (приход/расход/перемещение). Поток событий,
  не финальное состояние; одно изменение остатка может породить несколько move'ов.
- **`stock.quant`** — материализованное финальное состояние остатка в локации.
  Inventory adjustment и валидация picking'а в итоге пишут именно сюда.
- **`product.product.qty_available`** — computed-поле (sum quants). НЕ триггерит
  `write` на product при stock.move → base.automation на product не сработает.

## Decision

**Слушаем `stock.quant` через `base.automation` (`on_create_or_write`),
`trigger_field_ids = [quantity]`.**

1. Нам нужно **состояние**, а не событие — quant его и хранит. Worker всё равно
   перечитывает свежий агрегат из Odoo (не доверяет телу webhook'а), так что
   множественные quant-write'ы по одному товару схлопываются.
2. **Только поле `quantity`**, НЕ `reserved_quantity`:
   - `reserved_quantity` меняется при резервах Odoo (picking/sale) — это
     внутренняя механика Odoo, витрине не нужна (Saleor сам трекает свой reserved).
   - Триггер на все поля дал бы 10× лишний шум (как ругалось в Phase 3.2
     hardening на широких триггерах).
3. **Subject события = `product.product`**, а не сам quant. Серверный action
   достаёт `record.product_id` и шлёт в middleware
   `{odoo_model:'product.product', odoo_id:<product_id>, action:'write'}`. Quant —
   лишь триггер «у этого товара изменился остаток». Так:
   - worker перечитывает текущий агрегат (устойчиво к удалённым/слитым quant'ам);
   - 5-сек bucket dedup в `/api/odoo-events` схлопывает burst write'ов по товару.

## Alternatives considered

- **Триггер на `stock.move`.** Отброшено: событие, а не состояние; шумно;
  пришлось бы дедуплицировать и всё равно перечитывать quant.
- **Триггер на `product.product` write.** Отброшено: `qty_available` computed,
  `write` на product при stock-движении не происходит → не сработает.
- **Слать тело quant'а (qty, location) в middleware.** Отброшено: тело может
  устареть к моменту обработки; перечитать агрегат надёжнее (ADR соответствует
  принципу «middleware не доверяет телу webhook'а», как в catalog-flow 3.2).

## Consequences

**Pros:** ловим реальные изменения остатка из всех источников (adjustment,
picking), минимум шума, устойчиво к гонкам и удалению quant'ов.

**Cons:** один товар с активной складской деятельностью генерит частые события —
смягчается 5-сек bucket dedup и тем, что worker делает один push на актуальный
агрегат. Перемещения между internal-локациями одного склада дают событие, но
агрегат не меняется → reconcile/push идемпотентен (no-op результат).
