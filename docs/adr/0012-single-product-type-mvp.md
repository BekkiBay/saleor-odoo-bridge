# ADR-0012: Одна Saleor ProductType "Generic" для всего каталога в Phase 3.2

## Status
Accepted (2026-05-23) — Phase 3.2

## Context

В Odoo стартовый каталог — 30 **simple products** (`product.template` без
вариантов/атрибутов). В Saleor товар обязан иметь `ProductType` и хотя бы один
`ProductVariant` (цена и SKU живут на варианте, не на продукте).

Полноценный маппинг Odoo attributes/values → Saleor variant-attributes — это
Phase 3.5. В 3.2 он не нужен и только раздул бы код.

## Decision

- **Один `ProductType` "Generic"** на весь каталог. Имя берётся из
  `BRIDGE_SALEOR_PRODUCT_TYPE_NAME` (default `Generic`). Создаётся get-or-create,
  ID кэшируется в `saleor.binding` (`model_name='product.type'`, `odoo_id=0`).
- Создаётся **без variant-атрибутов** и без product-атрибутов → у продукта может
  быть один «пустой» вариант.
- Каждый Odoo `product.template` → один Saleor `Product` + **один dummy
  `ProductVariant`** с тем же SKU (`default_code`). Цена и channel-listing — на этом
  варианте.
- `kind = NORMAL`, `isShippingRequired = true`, `hasVariants = false`.

## Alternatives considered

- **ProductType per Odoo-категория.** Отброшено: YAGNI, усложняет маппинг без
  бизнес-ценности в MVP. Категория уже выражается через Saleor `Category`.
- **Configurable product (variants) сразу.** Отброшено: это Phase 3.5; в Odoo пока
  нет вариантов для синка.

## Consequences

**Pros:** простой, предсказуемый маппинг 1 product → 1 product + 1 variant. Легко
менять цену/SKU. Один тип — нет накладных расходов на типы.

**Cons:** когда в Phase 3.5 появятся варианты, продукты, созданные как single-variant
«Generic», придётся мигрировать на типы с атрибутами (variant id меняется → re-map
binding). Это известный долг, помечен в Phase 3.5.

**Supersedes-hint:** при вводе вариантов завести ADR «ProductType per attribute-set»
со ссылкой `Supersedes ADR-0012`.
