# Runbook — Order lifecycle Odoo ↔ Saleor

Full order lifecycle between the storefront and the backoffice. Complements
the existing Saleor → Odoo order flow (checkout/payment webhooks). See
ADR-0019..0022.

## Full flow

```
Saleor (storefront)                      Odoo (backoffice)
────────────────                         ─────────────────
checkout → ORDER_CREATED    ──webhook──▶ sale.order draft           (existing)
payment  → ORDER_FULLY_PAID ─webhook──▶  action_confirm → 'sale'    (existing, skip-guard)
                                                │
   UNFULFILLED  ◀───orderConfirm──────  state 'sale'                ← this runbook
   FULFILLED + tracking ◀─orderFulfill─  picking 'done'             ← this runbook
   CANCELED  ◀──────orderCancel────────  state 'cancel'             ← this runbook
```

**Event → mutation** (the worker re-reads state from Odoo, ADR-0019):

| Odoo event | Saleor mutation | Idempotency pre-check |
|--------------|----------------|----------------------|
| sale.order → `sale` | `orderConfirm` | only if status is UNCONFIRMED |
| sale.order → `cancel` | `orderCancel` | skip if CANCELED; refuse if FULFILLED |
| picking → `done` | `orderFulfill` (+ tracking) | skip if FULFILLED |
| manual payment | `orderMarkAsPaid` | skip if already paid |

## Preconditions

1. The existing order-creation, catalog, and stock sync flows are working
   (orders are created Saleor→Odoo, catalog + stock are in place).
2. `saleor_sync` module v0.4.0 (order/picking automations):
   ```bash
   docker compose exec odoo odoo -c /tmp/odoo.conf -d marketplace -u saleor_sync --stop-after-init --no-http
   docker compose restart odoo
   ```
3. The Saleor App has MANAGE_ORDERS (for orderFulfill/Confirm/Cancel) — part of the app manifest.

## Operator flow (typical order)

1. **Customer checks out and pays** on the storefront → the order
   automatically appears in Odoo as a `sale.order` in state `sale`
   (confirmed). Storefront: UNFULFILLED.
2. **A manager picks the order** → opens the delivery picking, sets
   quantities, and if available, fills in `carrier_tracking_ref` (tracking
   number).
3. **Validates the picking** (the "Validate" button) → state `done`. After
   ~5s, the storefront shows: **FULFILLED**, the fulfillment has a
   trackingNumber set, and the customer gets a "shipped" email
   (`notifyCustomer=True`, ADR-0022).
4. **Cancellation** (if needed): `Cancel` on the sale.order → state `cancel`
   → storefront CANCELED. ⚠️ an already-shipped (FULFILLED) order cannot be
   canceled this way — that's a return (out of scope for this runbook); the
   middleware will log it and not fail.

## Reverse-echo guard (ADR-0020) — why there's no loop

When the order-confirmation flow confirms an order from a Saleor webhook, it
calls Odoo's `action_confirm` with `context={'saleor_sync_skip': True}`. The
outbound automation sees the flag and does NOT emit the event back — the echo
is broken. A manual state change in Odoo (not triggered from Saleor) carries
no such flag, so it does get pushed to the storefront (as intended).

## Verification

```graphql
# order status + fulfillments + tracking
query{ order(id:"<ORDER_ID>"){
  number status isPaid paymentStatus
  fulfillments{ id status trackingNumber lines{ quantity orderLine{ productSku } } }
  lines{ productSku quantity quantityFulfilled }
}}
```

```bash
# did the event arrive? (Odoo outbox)
# saleor.outbox for sale.order / stock.picking — state confirmed/200
# did the worker process it?
docker compose logs --since 2m middleware-worker | grep -E "order_state_synced|picking_synced|order_confirmed|order_fulfilled"
```

## Troubleshooting

| Symptom | Cause | Action |
|---------|---------|----------|
| Storefront status doesn't change | automation didn't fire / no binding | is there a `saleor.outbox` record? does the order have a `saleor.binding(sale.order)`? (the order must have originated from Saleor) |
| `orderConfirm` is a no-op | order is already not UNCONFIRMED | fine, that's idempotency working as intended |
| Cancel "cannot cancel FULFILLED" | order already shipped | that's a return, not a cancellation (out of scope) — handle it manually |
| Fulfill "nothing to fulfill" | lines already fulfilled / SKU mismatch | check that `productSku` in the Saleor order matches `default_code` in Odoo |
| Tracking empty on the storefront | `carrier_tracking_ref` not filled in on the picking | fill it in before validating |
| **Duplicate/looping statuses** | skip-guard didn't fire | check that confirm/cancel calls carry the `saleor_sync_skip` context (ADR-0020) |

## Known limitations

- **One full fulfillment per order** (ADR-0021). Partial/multi-box shipments
  and backorders are future work.
- **Reverse (`fulfillmentCancel`)** on a fulfillment cancellation is a NO-OP in the MVP.
- **Returns** (from Odoo) and **order edit** (line changes after confirm) are
  out of scope.
- **notify** is only controlled on `orderFulfill`; confirm/cancel
  notifications follow Saleor's own settings (ADR-0022).
