# ADR-0010: Stock consistency via a safety buffer + reconcile cron

## Status
Accepted (2026-05-21)

## Context

The source of truth for stock is Odoo (`stock.quant`). Saleor is the storefront — it displays whatever quantity we pushed to it.

Race-condition oversell scenario:
1. Saleor shows qty=1.
2. Two customers check out at the same time → 2 × `ORDER_CREATED`.
3. Both webhooks hit the middleware → queue_job → Odoo `sale.order.create`.
4. Odoo reserves the single qty=1 unit against both orders. One picking won't be able to ship.

A full solution would be a transactional stock check on Saleor's side (`productVariant.trackInventory=True` + reservation at checkout). This reduces the race but doesn't eliminate it: there's still a delay between checkout and Odoo confirmation, plus concurrent Odoo writes.

## Decision

**Layered defenses, with residual risk accepted:**

1. **Saleor stock reservation enabled** — `ProductVariant.trackInventory=True` by default in our syncs. Saleor's checkout-time reservation shrinks the race window down to roughly the duration of a checkout.

2. **Safety buffer on push.** When Odoo pushes `productVariantStocksUpdate` to Saleor, we send `max(qty - SAFETY_BUFFER, 0)`, where `SAFETY_BUFFER` is configurable (env `BRIDGE_STOCK_SAFETY_BUFFER`, default `1`). For hot SKUs we lose 1 unit of "virtually available" stock, but avoid oversell in the edge case.

3. **Reconcile cron** — every 5 minutes (configurable via `BRIDGE_STOCK_RECONCILE_INTERVAL`, default `300s`) the middleware bulk-reads:
   - Odoo: `stock.quant where location_id.usage='internal'` grouped by product_id → sum quantity.
   - Saleor: `productVariants(first:100, channel:"default-channel") { stocks { quantity warehouse { slug } } }`.
   - Diff: for each (variant, warehouse) pair, if |odoo_qty - saleor_qty| > threshold, re-push.
   - Log `event=stock_reconcile_drift`, with a count-per-run metric.

4. **We do not attempt** real-time (<1s) sync — that would require synchronous webhooks from Odoo with a round trip to Saleor inside the transaction, which risks deadlocks.

None of this is implemented yet at this stage (only a mock smoke test exists so far). This ADR fixes the policy so the stock-sync implementation work has clear guidance to follow.

## Alternatives considered

1. **Saleor as the source of truth for stock.** Every sale decrements Saleor stock, and Odoo catches up via webhook. **Rejected:** breaks the invariant that Odoo is the back-office single source of truth, which was established as a project invariant from the outset.

2. **Optimistic locking on Odoo `sale.order.create`**, checking `qty_available >= ordered_qty` and raising if not. **Rejected** for now: complicates the mapping, and by the time `create` runs in Odoo the stock may already have moved (race). Worth revisiting in a future iteration.

3. **No safety buffer, rely on reservation alone.** **Rejected:** Saleor's `quantityReserved` exists but resets on abandoned checkouts (TTL ~10 minutes) — during that window someone else can still buy the item.

## Consequences

**Pros:**
- Reduces the oversell rate to an acceptable level (expected <0.5% of orders).
- The reconcile cron is a safety net for lost webhooks.
- The buffer is configurable — a per-SKU policy can be set up later.

**Cons:**
- We "virtually" lose `SAFETY_BUFFER × number of SKUs` units of visible stock. For a 30-SKU test catalog, that's 30 units.
- The reconcile cron adds load on Odoo and Saleor every 5 minutes (bulk read).
- An edge case remains: a simultaneous sale of the very last unit when `SAFETY_BUFFER=0`.

**Mitigation:**
- `SAFETY_BUFFER=0` only for SKUs where stock is reliably large (>20). A per-SKU override via a product `x_safety_buffer` field is a future enhancement.
- The reconcile interval is tunable — it can be raised to once an hour under light load.
- A future operations dashboard could chart "stock drift events per hour."
