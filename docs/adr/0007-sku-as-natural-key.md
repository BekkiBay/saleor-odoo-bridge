# ADR-0007: SKU как natural key, Odoo ID как fallback через mapping table

## Status
Accepted (2026-05-21)

## Context

При получении из Saleor `OrderLine` нужно найти соответствующий `product.product` в Odoo. Два варианта:

1. **По SKU:** `product.product.default_code == OrderLine.productSku`. Human-readable, переживает миграции, но `default_code` not-unique by SQL constraint (unique только по convention).
2. **По internal ID через mapping:** lookup в `saleor.binding` где `saleor_id == OrderLine.variant.id`.

Стартовый каталог (30 товаров из xlsx) — все имеют SKU вида `SKU-001..030`. Они валидируются как unique при импорте через `lib/products.py`. Будущие импорты также через SKU. Saleor ProductVariant.sku — обязательное поле, мы его всегда заполняем.

## Decision

**Primary key для resolve product variant: SKU.**

```python
def resolve_variant(saleor_sku: str, saleor_id: str) -> int | None:
    Tmpl = env['product.product']
    # 1. Try SKU
    ids = Tmpl.search([('default_code', '=', saleor_sku)], limit=2)
    if len(ids) == 1:
        return ids[0]
    if len(ids) > 1:
        log.warning("SKU collision in Odoo", sku=saleor_sku, ids=ids)
        # fall through to mapping
    # 2. Try mapping table
    binding = env['saleor.binding'].search([
        ('model_name', '=', 'product.product'),
        ('saleor_id', '=', saleor_id),
    ], limit=1)
    if binding:
        return binding.odoo_id
    return None
```

**При создании binding** заполняем оба: SKU и `saleor.binding` row. SKU — для быстрого happy-path lookup, mapping — для edge cases (SKU collision, SKU change, manual data fix).

**SKU collision policy:** если в Odoo появилось 2+ `product.product` с одинаковым `default_code` — это data quality bug. Логируем WARNING + Slack alert + fall back на mapping. Не падаем.

## Alternatives considered

1. **Only mapping table, ignore SKU.** **Отброшено:** mapping = индексный read на каждый lookup. SKU search — тот же индекс (`default_code` индексирован), но проще для human debugging ("найди мне товар X в обеих системах").

2. **Only SKU, no mapping.** **Отброшено:** SKU потеряли → весь sync поломан. Mapping = безопасность.

3. **Composite key (SKU + barcode + name).** **Отброшено:** YAGNI. Усложнение без бизнес-ценности.

## Consequences

**Pros:**
- Fast lookup happy path (SKU index).
- Survives Odoo migrations (XMLIDs могут сбиться при импорте-экспорте, SKU — нет).
- Human-debuggable: оператор видит SKU в обеих системах.

**Cons:**
- SKU mutable в Odoo — если оператор поменял `default_code` → sync поломан до ручного fix mapping.
- SKU collision (два товара с одинаковым default_code) — data bug, требует human intervention.

**Mitigation:**
- В Odoo module `saleor_sync` добавить SQL constraint **`unique(default_code) WHERE active=true`** (Phase 3.2 task, не Phase 3.0). Это enforce'ит uniqueness на новые данные.
- При наблюдении SKU change in Odoo (через `base.automation` on `product.product` write) — auto-update `saleor.binding.last_sync_*` + trigger re-sync.
