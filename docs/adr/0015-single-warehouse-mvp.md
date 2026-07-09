# ADR-0015: Single-warehouse MVP (1 Odoo warehouse → 1 Saleor warehouse)

## Status
Accepted (2026-05-23)

## Context

Odoo splits stock by `stock.location` within a `stock.warehouse`. A single product
can have several `stock.quant` records (different locations, lots/serials). Saleor
stores stock as `Stock(variant, warehouse, quantity)` — a single number per
(variant, warehouse) pair.

A full multi-warehouse mapping (several Odoo warehouses → several Saleor warehouses
+ shipping zones + channel allocation) is a substantial amount of work: location
mapping, choosing a warehouse per shipping zone, splitting stock levels. For the
current catalog (30 SKUs, a single physical warehouse) that would be
over-engineering.

## Decision

**One Odoo `stock.warehouse` ↔ one Saleor `Warehouse`.**

1. The middleware aggregates **all** internal quants for a product into a single
   number (`sum(quantity)` over `location_id.usage='internal'`), without splitting by
   location.
2. On the Saleor side, we reuse the **already-existing** Saleor `Warehouse` (the one
   Saleor creates at initialization, already tied to the `default-channel` shipping
   zone). The mapping from the Odoo warehouse to this Saleor warehouse is stored in
   `saleor.binding` with `model_name='stock.warehouse'` (see ADR-0007 — we reuse the
   binding infrastructure instead of introducing a new model).
3. If Saleor has no warehouse at all, we create a new one with slug
   `{odoo_code}-{odoo_id}` (guaranteeing uniqueness — see the known pitfalls of the
   stock-sync work). But in the normal MVP flow we attach to the existing warehouse,
   so stock immediately shows up in `quantityAvailable(channel)` without a manual
   warehouse↔channel link.

## Alternatives considered

- **Create a separate Saleor warehouse per Odoo warehouse.** Rejected for the MVP: a
  new warehouse isn't linked to the channel's shipping zone, so
  `quantityAvailable` in the channel would be 0 — the product would show as "out of
  stock" despite having inventory. This would require warehouse↔shippingZone↔channel
  wiring. Reusing the default warehouse avoids this problem entirely.
- **Multi-warehouse from the start.** Rejected: no business need yet (a single
  warehouse), and it would have bloated the stock-sync work. Deferred to a future
  iteration.

## Consequences

**Pros:** a simple mapping, stock is immediately visible in the channel, zero new
Odoo code (we reuse `saleor.binding`).

**Cons:** when a second Odoo warehouse appears, its stock will collapse into the
single Saleor warehouse (losing the per-location breakdown). This is addressed later
by a proper multi-warehouse mapping. `fetch_aggregated_stock` already returns
`list[StockLevel]` (per warehouse), so extending to multi-warehouse is additive.
