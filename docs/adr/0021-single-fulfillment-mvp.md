# ADR-0021: Single full fulfillment per order (MVP)

## Status
Accepted (2026-05-23)

## Context

Odoo allows multiple `stock.picking` records per `sale.order` (partial shipments,
backorders, multi-package delivery). Saleor supports multiple `Fulfillment` records
per order. A full partial-fulfillment mapping (tracking how much of each line has
shipped, which picking maps to which fulfillment, backorders) is a significant
amount of work and state to manage.

For the current MVP, an order ships as a single picking in full.

## Decision

**One full fulfillment per order.**

- When `picking.state = done`, we push `orderFulfill` for the lines on that picking
  (`move_line_ids` → SKU → Saleor `OrderLine`), with quantity =
  `quantityToFulfill` (whatever hasn't shipped yet).
- If the order is already fully `FULFILLED`, skip (idempotency).
- If only part of the order has shipped, Saleor will show
  `PARTIALLY_FULFILLED` (correct behavior, but we do NOT deliberately orchestrate
  multiple pickings — that's a side effect, not a supported scenario).
- `fulfillmentCancel` (reversing a shipment) is a **NO-OP** for now.

## Alternatives considered

- **Full partial-fulfillment support with a picking↔fulfillment mapping.**
  Rejected for now: requires storing the picking→fulfillment id correspondence and
  handling backorders. Deferred to a future iteration.
- **Disallow partial shipments in Odoo.** Rejected: we shouldn't break the
  operator's backoffice workflow just to simplify the storefront side.

## Consequences

**Pros:** simple and predictable fulfillment, covering the main case (ship it, and
the customer sees "Fulfilled" + tracking).

**Cons:** multiple partial shipments of the same order aren't orchestrated right now
(each `done` picking sends its own `orderFulfill` for the remaining lines; complex
scenarios can produce inconsistencies). Reverse fulfillment (`fulfillmentCancel`),
multi-package shipments, and backorders are deferred to a future iteration —
documented here as explicitly out of scope for now.
