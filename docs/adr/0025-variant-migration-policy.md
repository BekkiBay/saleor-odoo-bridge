# ADR-0025: Migration policy для existing single-variant продуктов

## Status
Accepted (2026-05-23) — Phase 3.5. Закрывает долг из ADR-0012.

## Context

После Phase 3.2 в Saleor 30 продуктов, у каждого один dummy `ProductVariant`
(SKU = `template.default_code`, ADR-0012). Bindings есть только на уровне
`product.template`; на `product.product` (вариант) — НЕТ. Phase 3.5 вводит
per-variant bindings и multi-variant. Нельзя сломать 30 живых продуктов и активные
заказы (SKU стабилен, ADR-0024).

## Decision

Авторитетная реконсиляция набора вариантов (`sync_template_variants_to_saleor`):
desired (active `product.product` шаблона) vs current (Saleor variants), diff по SKU.

1. **Single-variant без атрибутов** → desired = [1 вариант, SKU = template SKU] =
   current (dummy). Совпадение по SKU → **adopt**: создаём binding
   `product.product` → существующий dummy-вариант. Saleor НЕ меняется. Цена
   переустанавливается (idempotent).
2. **Template получает атрибуты** → Odoo пересоздаёт `product.product` (новые SKU).
   desired = новые варианты, current = старый dummy. Dummy SKU ∉ desired →
   **delete** dummy; новые → **bulk create** с attribute-assignments.
3. **Initial migration** — CLI `bulk-seed-variants` прогоняет реконсиляцию по всем
   синканным шаблонам: 30 single-variant продуктов получают variant bindings.
4. **Self-healing** — даже без CLI: первое же событие на `product.product`
   (правка/остаток) усыновляет dummy и создаёт binding.

## Alternatives considered

- **Wipe + re-seed всего каталога.** Отброшено: ломает активные заказы и URL'ы,
  меняет все Saleor ID без нужды.
- **Per-variant unlink-триггер для удаления dummy.** Хрупко: Odoo при
  регенерации вариантов archive'ит/unlink'ает непредсказуемо. Реконсиляция по
  шаблону надёжнее (один authoritative diff).

## Consequences

**Pros:** zero-downtime миграция; идемпотентно; SKU/заказы не ломаются;
self-healing страхует от пропущенного CLI.

**Cons:** при переходе single→multi dummy пересоздаётся (delete+create) → новый
variant ID, остаток на нём пропадает → нужен **stock resync** после пересоздания
(см. подводные камни Phase 3.5: stock привязан к variant_id). Реконсиляция дёргает
stock-sync для новых вариантов через стандартный `product.product` flow.
