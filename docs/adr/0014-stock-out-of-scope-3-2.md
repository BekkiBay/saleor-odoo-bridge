# ADR-0014: Stock and warehouses out of scope for catalog sync (covered later by stock sync)

## Status
Accepted (2026-05-23)

## Context

Saleor allows creating a `Product` + `ProductVariant` **without** stock records
(`Stock` / `Warehouse`). Such a variant simply has no stock level; with
`allowUnpaidOrders` and without `trackInventory` it remains purchasable. Full stock
sync (stock levels, reservation, the reconcile cron, the safety buffer) is covered
separately by ADR-0010.

## Decision

Products created during catalog sync are created **without stock entries**:

- `ProductVariant.trackInventory = false` — Saleor doesn't block purchases based on
  stock level.
- No `stockUpdate` / `Warehouse` mutations.
- `quantityAvailable` in Saleor for these variants will be 0/not meaningful — that's
  fine for catalog sync (the goal here is just for the product to be visible and
  orderable in the storefront for end-to-end testing).

Real stock levels are added by the stock-sync work (see ADR-0010): a separate flow
from Odoo's `stock.quant` to Saleor's `Stock`, with a safety buffer and a reconcile
cron.

## Alternatives considered

- **Explicitly create stock=0.** Rejected: `trackInventory=false` is simpler and
  doesn't mark the product as "out of stock."
- **Pull in stock right away.** Rejected: that requires warehouse mapping and
  reconcile logic that belongs to the stock-sync work; doing it here would bloat this
  step unnecessarily.

## Consequences

**Pros:** simpler, fewer mutations, the product is immediately orderable for an
end-to-end demo.

**Cons:** until stock sync is implemented, Saleor has no real stock levels —
overselling isn't controlled on the Saleor side (Odoo remains the source of truth for
stock levels). This is a known, temporary gap, closed once stock sync ships.
