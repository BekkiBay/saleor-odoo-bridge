# ADR-0027: Attribute input type — DROPDOWN only в MVP

## Status
Accepted (2026-05-23) — Phase 3.5.

## Context

Saleor поддерживает много типов атрибутов: `DROPDOWN`, `MULTISELECT`, `NUMERIC`,
`RICH_TEXT`, `PLAIN_TEXT`, `BOOLEAN`, `DATE`, `DATE_TIME`, `FILE`, `REFERENCE`,
`SWATCH`. У Odoo `product.attribute.display_type` — `radio`/`select`/`color`/`pills`,
плюс `product.attribute.value.html_color` для swatch.

Для каталога одежды MVP нужны размер/цвет/материал — все выбираются из конечного
списка значений.

## Decision

- **Все атрибуты синкаем как `inputType: DROPDOWN`**, независимо от Odoo
  `display_type`. `domain.Attribute.input_type = Literal["DROPDOWN"]`.
- **`type: PRODUCT`, `valueRequired: false`** — чтобы single-variant продукты
  держали вариант без значений атрибутов (миграция, ADR-0025).
- Variant attribute value передаём как `dropdownValue: {id: <AttributeValue id>}`.
- **`html_color` НЕ синкаем** в MVP (может быть пустым; swatch — Phase 4).
- **`create_variant = 'no_variant'` атрибуты скипаем** (это product-level
  «состав: 100% хлопок», не variant-defining) — Phase 4.

## Alternatives considered

- **Маппить display_type → inputType (color→SWATCH, etc.).** Отброшено: SWATCH
  требует hex/файл, добавляет ветвление в create/resolve без ценности в MVP.
- **NUMERIC для размеров обуви.** Отброшено: размеры выбираются из списка, DROPDOWN
  достаточно; NUMERIC усложнил бы резолв значений.

## Consequences

**Pros:** одна форма мутаций (create attribute, create value, assign, variant
attributes) — минимум ветвления; предсказуемо.

**Cons:** цветовые свотчи на витрине будут текстом («Red»), не плашкой цвета — UX
долг, закрывается Phase 4 (SWATCH + html_color). Числовые/текстовые атрибуты пока
недоступны. Помечено как out of scope.
