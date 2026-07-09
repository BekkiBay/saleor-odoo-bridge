# ADR-0019: Order status mapping Odoo → Saleor

## Status
Accepted (2026-05-23)

## Context

Order sync (see ADR-0005, ADR-0007, ADR-0008) syncs orders Saleor → Odoo
(created/paid/cancelled). The reverse direction (order status Odoo → storefront) was
missing: the customer never saw "shipped"/"cancelled." This ADR closes the loop for
Odoo → Saleor across the order lifecycle: confirm, fulfillment (shipping), cancel,
manual payment.

The Saleor order state machine is **strict** — mutations are only valid from certain
statuses (you can't call `orderConfirm` on an already-confirmed order). So every
mutation requires an idempotency pre-check of the current status (see the pitfalls
noted below).

## Decision

The trigger is Odoo's `base.automation` `on_state_set` on `sale.order.state` and
`stock.picking.state` (this precisely catches state-machine transitions, without
noise). The event subject is the model + odoo_id; the worker **re-reads** the
current state from Odoo and decides the mutation (as in ADR-0017: state, not event).

### sale.order.state

| Odoo state | Saleor status (pre-check) | Mutation | Note |
|------------|---------------------------|---------|------------|
| `sale` (draft→sale) | UNCONFIRMED → | `orderConfirm(id)` | if not already UNCONFIRMED → skip (no-op) |
| `cancel` | not CANCELED → | `orderCancel(id)` | FULFILLED → cannot be cancelled, log + graceful skip |
| `done` (locked) | — | NO-OP | Saleor has no equivalent of "locked"; already covered by the fulfilled status |

In this version of Saleor, `orderConfirm` takes **no** `isPaid` argument (an earlier
draft of the design spec got this wrong) — it's simply `orderConfirm(id)`. Payment is
already synced by the order-sync flow (ORDER_FULLY_PAID).

### stock.picking.state

| Odoo state | Saleor status (pre-check) | Mutation |
|------------|---------------------------|---------|
| `done` (shipped) | not FULFILLED → | `orderFulfill(order, input:{lines, notifyCustomer, allowStockToBeExceeded:false, trackingNumber})` |
| `cancel` (reverse) | — | NO-OP for now (`fulfillmentCancel` is a future enhancement) |

`trackingNumber` (`carrier_tracking_ref`) is passed **inside** `OrderFulfillInput`
(no separate tracking mutation is needed). `None` is acceptable.

Fulfillment line mapping: Odoo `stock.move.line.product_id.default_code` (SKU) →
Saleor `OrderLine` via `productSku` → `orderLineId` + `stocks:[{quantity, warehouse}]`.
The warehouse is the same Saleor warehouse as in ADR-0015 (the `stock.warehouse`
binding).

### account.move payment_state

| Odoo payment_state | Mutation |
|--------------------|---------|
| → `paid` (manual in Odoo) | `orderMarkAsPaid(id)` if `paymentStatus != FULLY_CHARGED` |

Note: almost all payments are already synced by the order-sync flow (the customer
pays on the storefront). This ADR covers **manual payment entered in the
backoffice** — a rare case. An idempotency check is mandatory (usually a no-op).

## Consequences

**Pros:** the customer sees the real order status
(confirmed/fulfilled/cancelled/tracking); a single source of truth for
operations — the Odoo backoffice.

**Cons:** the strict Saleor state machine requires a pre-check before every mutation
(+1 query). Partial fulfillment isn't covered (ADR-0021). The reverse-echo risk
requires a skip-guard (ADR-0020).
