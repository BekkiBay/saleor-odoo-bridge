# ADR-0016: Safety buffer = MAX(qty - buffer, 0) на push

## Status
Accepted (2026-05-23) — Phase 3.3. Подтверждает и конкретизирует ADR-0010.

## Context

ADR-0010 зафиксировал многоуровневую защиту от oversell, включая safety buffer.
Phase 3.3 имплементирует stock sync — нужно точно зафиксировать формулу, место
применения и поведение на краевых значениях (0, отрицательный остаток).

Race oversell остаётся возможен: между показом остатка в Saleor и резервом в Odoo
есть задержка; параллельные checkout'ы могут увести последнюю единицу дважды.

## Decision

**На каждый push остатка в Saleor применяем `available = MAX(raw - buffer, 0)`,**
где `raw` — агрегированный остаток из Odoo (sum internal quants, см. ADR-0015),
`buffer = BRIDGE_STOCK_SAFETY_BUFFER` (env, дефолт `1`).

- Формула применяется **в домене** (`StockLevel.available_quantity`) —
  единственная точка, через которую проходит любой push (event-sync, bulk-seed,
  reconcile). Нет пути, минующего buffer.
- `MAX(..., 0)` одновременно служит **clamp'ом отрицательного остатка**: Odoo
  может показать `qty < 0` (inventory adjustment, backorder) — в Saleor уходит `0`,
  не ошибка (см. hardening S3).
- Остаток `raw` хранится в `StockLevel.raw_quantity` как есть (для reconcile-диффа
  и observability), buffer применяется только на выходе.

Примеры (buffer=1): `20 → 19`, `15 → 14`, `1 → 0`, `0 → 0`, `-3 → 0`.

## Alternatives considered

- **Percent-based buffer (`raw * 0.95`).** Отброшено: для малых остатков (1-2 шт)
  процент бессмыслен; абсолютный -1 предсказуем.
- **Buffer на стороне Odoo (computed field).** Отброшено: buffer — это политика
  витрины, ей место в middleware ближе к push; Odoo остаётся источником истины по
  raw-остатку.
- **Без buffer, полагаясь на Saleor reservation.** Отброшено в ADR-0010
  (reservation сбрасывается по TTL).

## Consequences

**Pros:** одна формула, одна точка применения, предсказуемо, заодно решает
negative-clamp. Configurable per-deploy через env.

**Cons:** «виртуально» теряем `buffer × число SKU` единиц видимого ассортимента
(на 30 SKU с buffer=1 — 30 единиц). Горячие SKU с остатком 1 показываются как
«нет в наличии». Per-SKU override — Phase 4 (ADR-0010 mitigation).
