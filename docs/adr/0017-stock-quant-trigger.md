# ADR-0017: Stock trigger = `stock.quant` write (field `quantity`)

## Status
Accepted (2026-05-23)

## Context

We need to catch stock changes in Odoo and push them to Saleor. Candidates:

- **`stock.move`** — a movement event (receipt/issue/transfer). A stream of events,
  not a final state; a single stock change can spawn several moves.
- **`stock.quant`** — the materialized final state of stock at a location. Both
  inventory adjustments and picking validation ultimately write here.
- **`product.product.qty_available`** — a computed field (sum of quants). It does
  NOT trigger a `write` on the product when a stock.move happens → a
  `base.automation` on the product wouldn't fire.

## Decision

**Listen on `stock.quant` via `base.automation` (`on_create_or_write`), with
`trigger_field_ids = [quantity]`.**

1. We need **state**, not an **event** — a quant holds exactly that. The worker
   always re-reads the fresh aggregate from Odoo (it doesn't trust the webhook body),
   so multiple quant writes for the same product collapse into one push.
2. **Only the `quantity` field**, NOT `reserved_quantity`:
   - `reserved_quantity` changes on Odoo-side reservations (picking/sale) — that's
     internal Odoo mechanics the storefront doesn't need (Saleor tracks its own
     reservations).
   - Triggering on all fields produced 10x more noise (as observed during hardening
     of overly broad triggers).
3. **The event subject is `product.product`**, not the quant itself. The server
   action reads `record.product_id` and sends the middleware
   `{odoo_model:'product.product', odoo_id:<product_id>, action:'write'}`. The quant
   is only the trigger for "this product's stock changed." As a result:
   - the worker re-reads the current aggregate (robust against deleted/merged
     quants);
   - the 5-second bucket dedup in `/api/odoo-events` collapses bursts of writes for
     the same product.

## Alternatives considered

- **Trigger on `stock.move`.** Rejected: it's an event, not a state; noisy; we'd
  still have to dedup and re-read the quant anyway.
- **Trigger on `product.product` write.** Rejected: `qty_available` is computed, so
  `write` on the product doesn't fire on stock movement → wouldn't trigger.
- **Send the quant's own body (qty, location) to the middleware.** Rejected: the
  body could be stale by the time it's processed; re-reading the aggregate is more
  reliable (consistent with the principle that the middleware never trusts a webhook
  body, as in the catalog-sync flow).

## Consequences

**Pros:** catches real stock changes from every source (adjustment, picking), with
minimal noise, and is robust against races and quant deletion.

**Cons:** a product with heavy warehouse activity generates frequent events —
mitigated by the 5-second bucket dedup and by the worker always pushing a single,
up-to-date aggregate. Transfers between internal locations of the same warehouse
still fire an event, but the aggregate doesn't change → the reconcile/push is
idempotent (a no-op result).
