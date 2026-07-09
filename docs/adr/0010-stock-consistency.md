# ADR-0010: Stock consistency через safety buffer + reconcile cron

## Status
Accepted (2026-05-21)

## Context

Source-of-truth по стоку = Odoo (`stock.quant`). Saleor — витрина, отображает количество которое мы pushed туда.

Race condition oversell:
1. Saleor показывает qty=1.
2. Два клиента одновременно checkout → 2 × `ORDER_CREATED`.
3. Оба webhook'а летят в middleware → queue_job → Odoo `sale.order.create`.
4. Odoo резервирует на двух order'ах единицу qty=1. Один picking не сможет ship.

Полное решение = transactional stock check на стороне Saleor (Saleor's `productVariant.trackInventory=True` + reservation на checkout). Это снижает race, но не убирает: задержка между checkout и Odoo confirm + параллельные Odoo writes.

См. [research doc §8 R1](../phase-3-integration-research.md#r1-eventual-consistency--oversell-на-стоке).

## Decision

**Многоуровневая защита, accept residual risk:**

1. **Saleor stock reservation включён** — `ProductVariant.trackInventory=True` по дефолту в наших sync'ах. Saleor reservation на checkout снижает race window до ~минут (длительность checkout).

2. **Safety buffer на push.** Когда Odoo пушит `productVariantStocksUpdate` в Saleor, передаём `max(qty - SAFETY_BUFFER, 0)`, где `SAFETY_BUFFER` configurable (env `BRIDGE_STOCK_SAFETY_BUFFER`, дефолт `1`). На горячих SKU теряем 1 unit "виртуально доступного", но избегаем oversell на edge case.

3. **Reconcile cron** — раз в 5 минут (configurable `BRIDGE_STOCK_RECONCILE_INTERVAL`, default `300s`) middleware bulk-reads:
   - Odoo: `stock.quant where location_id.usage='internal'` group by product_id → sum quantity.
   - Saleor: `productVariants(first:100, channel:"default-channel") { stocks { quantity warehouse { slug } } }`.
   - Diff: для каждой пары (variant, warehouse) если |odoo_qty - saleor_qty| > threshold → re-push.
   - Лог `event=stock_reconcile_drift`, метрика count per run.

4. **Не пытаемся** делать real-time sync (<1s) — это потребовало бы sync webhook'ов из Odoo с round-trip к Saleor в transaction, что чревато deadlocks.

В **Phase 3.0** ни одно из этого ещё не имплементировано (mock smoke только). Решение фиксируется чтобы Phase 3.3 (stock sync) знала policy.

## Alternatives considered

1. **Saleor как source-of-truth для стока.** Каждая продажа уменьшает Saleor stock, Odoo догоняет через webhook. **Отброшено:** ломает invariant "Odoo = back-office single source of truth", который заказчик зафиксировал в Phase 0 контексте.

2. **Optimistic locking на Odoo `sale.order.create`** с проверкой `qty_available >= ordered_qty`, raise если нет. **Отброшено** для Phase 3: усложняет mapping, плюс к моменту create в Odoo stock уже мог уйти (race). Phase 4 — рассмотреть.

3. **No safety buffer, polagaem на reservation.** **Отброшено:** Saleor `quantityReserved` существует но reset'ится на abandoned checkouts (TTL ~10 минут) — за это время кто-то ещё может купить.

## Consequences

**Pros:**
- Снижение oversell rate до приемлемого уровня (по ожиданию <0.5% заказов).
- Reconcile cron — safety net на случай потерянного webhook.
- Configurable buffer — заказчик может настроить per-SKU policy позже.

**Cons:**
- "Виртуально" теряем `SAFETY_BUFFER × число SKU` единиц видимого ассортимента. На 30 SKU тестового каталога — 30 единиц.
- Reconcile cron = +нагрузка на Odoo и Saleor каждые 5 минут (bulk read).
- Edge case остаётся: одновременная продажа последнего из 1 unit'а с `SAFETY_BUFFER=0`.

**Mitigation:**
- `SAFETY_BUFFER=0` только для SKU где запас всегда большой (>20). Per-SKU override через продукт `x_safety_buffer` field (Phase 4).
- Reconcile интервал tunable — можно поднять до 1 часа при низкой нагрузке.
- Operations dashboard в Phase 4: график "stock drift events per hour".
