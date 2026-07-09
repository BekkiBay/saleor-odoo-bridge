# ADR-0026: Per-variant per-channel pricing (price_extra propagation)

## Status
Accepted (2026-05-23) — Phase 3.5.

## Context

В Odoo цена варианта = `template.list_price` + сумма `price_extra` по PTAV
(product.template.attribute.value), которые относятся к варианту. Готовое значение
лежит в `product.product.lst_price`. В Saleor цена живёт в
`ProductVariantChannelListing` per (variant, channel) (ADR-0004: один канал MVP).

Проблема триггера: `lst_price` на `product.product` — **non-stored compute** (это
подтверждено интроспекцией). base.automation не может триггерить на non-stored
поле. Значит «изменение цены варианта» нельзя поймать напрямую на варианте.

## Decision

- **Источник цены варианта = `lst_price`** (читаем готовое; не суммируем
  price_extra сами). `domain.Variant.price = product.product.lst_price`.
- **Push в `ProductVariantChannelListing`** через `productVariantChannelListingUpdate`
  (single update) либо inline `channelListings` в `productVariantBulkCreate`.
- **Триггеры цены — на источниках, не на lst_price:**
  - `product.template` write (включая `list_price`) → template-handler реконсилит
    цены всех вариантов;
  - `product.template.attribute.value.price_extra` (stored!) → эмитим событие
    `product.template` родителя → та же реконсиляция.
- Worker читает свежий `lst_price` из Odoo (после commit, 3s defer) — он уже
  пересчитан = `list_price + price_extra`.

## Alternatives considered

- **Триггер на `product.product.lst_price`.** Невозможно: поле non-stored compute.
- **Суммировать `list_price + price_extra` в middleware.** Дублирует логику Odoo,
  риск расхождения при сложных pricelist-правилах. `lst_price` — single source of truth.
- **Триггер на `product.product` для цены.** Не сработает: запись price_extra на
  PTAV не пишет в product.product.

## Consequences

**Pros:** цена всегда консистентна с Odoo (читаем lst_price); оба пути изменения
(list_price и price_extra) покрыты; reconcile переустанавливает цены идемпотентно.

**Cons:** правка одного PTAV.price_extra реконсилит ВСЕ варианты шаблона (а не
только затронутые). Для каталога одежды (3-5 размеров × 2-4 цвета) набор мал —
overhead незначим. Тонкая адресная адресация — Phase 4 при необходимости.
