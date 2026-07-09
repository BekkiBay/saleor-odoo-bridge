# ADR-0024: Variant SKU = product.product.default_code

## Status
Accepted (2026-05-23) — Phase 3.5. Расширяет ADR-0007 на уровень вариантов.

## Context

ADR-0007 закрепил SKU (`default_code`) как natural key между Odoo и Saleor на
уровне товара. Phase 3.5 опускает этот ключ на уровень варианта: каждый
`product.product` ↔ один Saleor `ProductVariant`. Saleor требует SKU **глобально
уникальным** (не per-product). Резолв заказов (Phase 3.1) уже идёт по
`product.product.default_code`.

## Decision

- **`ProductVariant.sku = product.product.default_code`.** Единственный natural key
  для резолва, диффа набора вариантов и переноса остатков при пересоздании.
- Если `default_code` пустой → **fallback `odoo-<product.product.id>`** (как у
  товаров в ADR-0007). Глобально уникален, стабилен.
- Оператор задаёт SKU вариантов вручную либо Odoo автогенерит по шаблону
  (`TEMPLATE-S-RED`). Мы не навязываем шаблон — читаем что есть.
- Реконсиляция набора вариантов (`sync_template_variants_to_saleor`) матчит
  desired (Odoo) и current (Saleor) **по SKU**: совпал → adopt/update, новый →
  create (bulk), лишний → delete.

## Alternatives considered

- **Variant id (Odoo) как ключ через metadata.** Отброшено: SKU и так нужен и уже
  natural key для заказов; второй ключ — дубль.
- **Composite key (template_sku + attribute combo).** Хрупко: переименование
  атрибута ломает ключ; SKU стабильнее.

## Consequences

**Pros:** один ключ для всего (catalog, variants, stock, orders); миграция
single-variant прозрачна (dummy SKU = template SKU = product.product SKU).

**Cons:** коллизия SKU между двумя `product.product` → один перезатрёт другого в
Saleor. Митигируем: fallback гарантирует уникальность, при ручном дубле — лог
`sku_collision` (как в order resolution). Контроль уникальности SKU — на стороне
оператора Odoo.
