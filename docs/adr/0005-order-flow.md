# ADR-0005: Order flow — ORDER_CREATED → draft, ORDER_PAID → confirm

## Status
Accepted (2026-05-21)

## Context

Saleor order lifecycle: `Checkout` → `ORDER_CREATED` (placed) → `ORDER_CONFIRMED` (admin) → `ORDER_PAID` / `ORDER_FULLY_PAID` → `ORDER_FULFILLED`.

Odoo `sale.order.state`: `draft` → `sent` → `sale` → `cancel`. (Odoo 19 removed `done` — it's now `state='sale' AND locked=True`.) The `draft → sale` transition via `action_confirm()` reserves stock, creates a `stock.picking`, and makes the SO visible on the operational dashboard.

We need to decide exactly when to create the `sale.order` and when to confirm it.

## Decision

**Two-phase mapping:**

1. **`ORDER_CREATED` → create a `sale.order` in `draft` state.**
   - `partner_id`, `partner_invoice_id`, `partner_shipping_id` are resolved via `res.partner` (created if missing).
   - `order_line` is populated with all SKUs.
   - `client_order_ref = saleor_order_number` for deduplication.
   - We do NOT call `action_confirm()` — the order sits on the sales operators' dashboard as an unconfirmed quote.

2. **`ORDER_PAID` / `ORDER_FULLY_PAID` → call `action_confirm()` + auto-invoice.**
   - Idempotent: if `state == 'sale'`, it's a no-op.
   - After confirm: `_create_invoices()` → `action_post()` → `account.payment.register`.

3. **`ORDER_CANCELLED` → call `_action_cancel()` in Odoo.**

4. **`ORDER_UPDATED`** (between created and paid) — updates the lines on the draft SO. After confirm, it's ignored (lines are already locked in).

## Alternatives considered

1. **`ORDER_PAID` → create+confirm at the same time.** The operator wouldn't see unpaid orders in Odoo, only paid ones. **Rejected:** we'd lose visibility into unconfirmed/expired orders for analytics ("how many orders went unpaid today").

2. **`ORDER_CREATED` → create + immediate confirm.** The sale order would reserve stock immediately, even before payment. **Rejected:** if a customer abandons payment, reserved stock stays locked until the cancel webhook arrives. Riskier for inventory accuracy.

3. **`ORDER_CONFIRMED` (admin confirmation in the Saleor Dashboard) → create in Odoo.** **Rejected:** manual order moderation in Saleor isn't used — all orders are auto-confirmed.

## Consequences

**Pros:**
- The operator sees the whole flow from placement to payment.
- Stock reservation only happens after an actual payment — no orphan reservations.
- A draft sale.order serves as an audit trail for "a customer tried to buy this."

**Cons:**
- Two webhooks instead of one — two places where sync can fail.
- Draft sale.orders accumulate for cancelled/expired orders — a cron-based cleanup will be needed eventually.

**Mitigation:**
- Idempotency: both webhooks upsert by `client_order_ref`. Duplicates don't create new entities.
- If `ORDER_PAID` arrives without a preceding `ORDER_CREATED` (race condition or a lost first event), we create the SO and confirm it immediately.

See also: [ADR-0009](0009-refunds-deferred.md) (cancel/refund flow deferred).
