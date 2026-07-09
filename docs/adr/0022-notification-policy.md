# ADR-0022: Customer notification policy on order mutations

## Status
Accepted (2026-05-23)

## Context

When syncing order status from Odoo to Saleor, we need to decide whether to email
the customer. Not every change matters to the customer: payment confirmation is a
technical transaction, whereas "your order has shipped" with a tracking number is an
important event.

The reality of this version of the Saleor schema limits our control:
- `orderFulfill(input: OrderFulfillInput)` — **has** a `notifyCustomer: Boolean`
  parameter.
- `orderConfirm(id)`, `orderCancel(id)`, `orderMarkAsPaid(id)` — **have no** notify
  parameter; whether these events trigger an email is controlled by Saleor's own
  settings (Shop/Channel).

## Decision

**We control notification where Saleor allows it — on `orderFulfill`:**

| Mutation | notify | How it's implemented |
|---------|--------|-----------------|
| `orderFulfill` | **True** | `OrderFulfillInput.notifyCustomer = True` (the customer cares about "shipped" + tracking) |
| `orderConfirm` | n/a | no such parameter; the confirmation email is governed by Saleor's own settings — we don't send an extra one |
| `orderCancel` | n/a | no such parameter; the cancellation notice is governed by Saleor's settings |
| `orderMarkAsPaid` | n/a (effectively False) | no such parameter; a silent backoffice operation |

`notify_customer` is passed as a parameter into the use case/adapter (default `True`
for fulfill) — configurable for the future, but in practice it currently only
affects `orderFulfill`.

## Alternatives considered

- **Notify on everything (notify=True everywhere).** Rejected: `confirm`/`markPaid`
  have no such Saleor parameter, and spamming the customer with technical emails is
  poor UX (where we do have control — on fulfill — we keep it True).
- **Notify on nothing (notify=False on fulfill).** Rejected: "your order has
  shipped" is a key email for the customer (it reduces "where's my order?" support
  tickets).

## Consequences

**Pros:** the customer gets a meaningful notification about shipment with a
tracking number; technical transactions aren't something we manually control
(Saleor handles those via its own settings).

**Cons:** confirm/cancel notifications are outside our direct control (they depend
on Saleor's settings) — if fine-grained control is ever needed, it would require
Saleor-side configuration work.
