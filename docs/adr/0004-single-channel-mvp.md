# ADR-0004: Single channel `default-channel` (UZS) для MVP

## Status
Accepted (2026-05-21)

## Context

Saleor моделирует мульти-площадку через `Channel` — каждый channel имеет свою currency, language, country, pricelist (`ProductVariantChannelListing.price`).

У нас сейчас один: `default-channel`, UZS, RU/UZ языки в одном UI. Заказчик — Узбекистан (B2C). Опт (B2B) и российская площадка пока вне scope.

Полная поддержка multi-channel в sync = N итераций `productVariantChannelListingUpdate` на каждый product update + N pricelist'ов в Odoo + N маппинговых записей. Это +30% сложности кода и +50% времени тестирования.

## Decision

**В Phase 3 — только один channel: `default-channel`.**

Конкретно это значит:
- Sync товаров создаёт ровно один `ProductChannelListing` и ровно один `ProductVariantChannelListing` per variant.
- Цена берётся из `product.template.list_price` (без pricelist lookup).
- Заказы фильтруются `channel.slug = 'default-channel'`.
- В `saleor.binding` нет колонки `channel_id`.

Multi-channel — отдельный ADR в Phase 4 (когда появится российская/опт площадка). Миграция будет non-breaking: добавим `channel_id`-поле в `saleor.binding` с дефолтом текущего, заполним для существующих записей.

## Alternatives considered

1. **Сразу делать мульти-channel-ready схему.** **Отброшено:** YAGNI. Усложнит Phase 3.1-3.5 без бизнес-выгоды сейчас.

2. **Один Saleor instance, два warehouse'а как proxy для multi-region.** **Отброшено:** warehouse ≠ channel в Saleor. Цены multi-region всё равно требуют channel.

## Consequences

**Pros:**
- Упрощённый sync-код (~30% меньше LOC).
- Меньше edge-cases (нет per-channel price override conflicts).
- Быстрее доставить MVP.

**Cons:**
- Когда понадобится RU-channel — будет одноразовая миграция (схема + данные).
- Hardcoded `channel.slug == 'default-channel'` в нескольких местах — придётся вычистить.

**Mitigation:** все hardcoded ссылки на `'default-channel'` в коде middleware идут через `Settings.saleor_default_channel: str = 'default-channel'`. Cleanup в Phase 4 = `grep -r saleor_default_channel` + замена на per-call параметр.
