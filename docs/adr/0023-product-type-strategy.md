# ADR-0023: Single "Generic" ProductType с variant-атрибутами

## Status
Accepted (2026-05-23) — Phase 3.5. Расширяет ADR-0012.

## Context

ADR-0012 завёл один ProductType "Generic" (`hasVariants=false`, без атрибутов) для
30 single-variant продуктов. Phase 3.5 вводит реальные варианты: размер × цвет ×
материал. В Saleor атрибуты живут на ProductType, варианты выбирают значения этих
атрибутов.

Вопрос: дробить ли каталог на ProductTypes (Clothing/Shoes/Accessories), каждый со
своим набором атрибутов, или держать всё на одном типе?

## Decision

- **Один ProductType "Generic"** на весь каталог (как в ADR-0012), но теперь
  `hasVariants=true` и со всеми variant-атрибутами.
- Все `product.attribute` из Odoo синкаются как **VARIANT-атрибуты** этого
  единственного типа (`productAttributeAssign(type: VARIANT, variantSelection: true)`).
- `hasVariants` флипается лениво в `ensure_product_type_has_variants` при первой
  синке атрибута (idempotent).

## Alternatives considered

- **ProductType per категорию/класс товара.** Отброшено: Odoo не моделирует
  «класс товара» отдельно от категории; пришлось бы выводить тип эвристически.
  Усложняет binding (нужен per-type ID) и миграцию. Бизнес-ценности в MVP нет —
  витрина одежды рендерит один набор атрибутов.
- **Атрибут на product-level вместо variant-level.** Не подходит: размер/цвет
  определяют именно вариант (цену, SKU, остаток), а не продукт.

## Consequences

**Pros:** простой маппинг `product.attribute` → один тип; не нужно резолвить тип
по товару; миграция single→multi variant не меняет ProductType.

**Cons:** Saleor рендерит ВСЕ variant-атрибуты для любого продукта типа "Generic"
(оператор в админке видит и Size, и Shoe-size на платье). Для витрины это не
проблема (показываются только атрибуты с реальными значениями вариантов). Если
понадобится строгая дифференциация — Phase 4 split с `Supersedes ADR-0023`.

**Trade-off:** меньше гибкости в обмен на простоту — осознанный выбор MVP.
