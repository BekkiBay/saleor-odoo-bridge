# ADR-0016: Safety buffer = MAX(qty - buffer, 0) on push

## Status
Accepted (2026-05-23). Confirms and refines ADR-0010.

## Context

ADR-0010 established layered defenses against oversell, including a safety buffer.
Implementing stock sync requires pinning down the exact formula, where it's applied,
and its behavior at edge values (0, negative stock).

Race-condition oversell remains possible: there's a delay between showing stock in
Saleor and reserving it in Odoo, and concurrent checkouts can both grab the last
unit.

## Decision

**On every stock push to Saleor we apply `available = MAX(raw - buffer, 0)`,**
where `raw` is the aggregated stock read from Odoo (sum of internal quants, see
ADR-0015), and `buffer = BRIDGE_STOCK_SAFETY_BUFFER` (env var, default `1`).

- The formula is applied **in the domain layer** (`StockLevel.available_quantity`) —
  the single choke point through which every push flows (event-driven sync, bulk
  seed, reconcile). There's no path that bypasses the buffer.
- `MAX(..., 0)` also serves as a **clamp for negative stock**: Odoo can show
  `qty < 0` (inventory adjustment, backorder) — Saleor receives `0` in that case, not
  an error (see hardening finding S3).
- The raw value is stored as-is in `StockLevel.raw_quantity` (for reconcile diffing
  and observability); the buffer is only applied on the way out.

Examples (buffer=1): `20 → 19`, `15 → 14`, `1 → 0`, `0 → 0`, `-3 → 0`.

## Alternatives considered

- **Percent-based buffer (`raw * 0.95`).** Rejected: meaningless for small stock
  levels (1-2 units); an absolute -1 is predictable.
- **Buffer applied on the Odoo side (a computed field).** Rejected: the buffer is a
  storefront-facing policy, and belongs in the middleware close to the push; Odoo
  stays the source of truth for the raw stock level.
- **No buffer, relying on Saleor reservation.** Rejected in ADR-0010 (reservation
  resets on TTL).

## Consequences

**Pros:** one formula, one point of application, predictable, and it also handles
the negative-clamp case. Configurable per deployment via env var.

**Cons:** we "virtually" lose `buffer × number of SKUs` units of visible stock (for
30 SKUs with buffer=1, that's 30 units). Hot SKUs with only 1 unit left show as "out
of stock." A per-SKU override is a future enhancement (see the ADR-0010 mitigation).
