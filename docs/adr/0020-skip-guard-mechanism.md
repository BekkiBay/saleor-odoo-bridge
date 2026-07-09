# ADR-0020: Reverse-echo prevention via skip-guard context

## Status
Accepted (2026-05-23). Extends the `saleor_sync_skip` mechanism introduced during catalog-sync hardening.

## Context

Order sync changes `sale.order` in Odoo in response to a Saleor webhook
(ORDER_FULLY_PAID → `action_confirm`). Order-status sync (ADR-0019) catches the
`sale.order.state` change and pushes it back to Saleor. Without protection, this
creates an **infinite loop**:

1. Saleor ORDER_FULLY_PAID → order sync calls `action_confirm` in Odoo.
2. Odoo state draft→sale → order-status automation → `orderConfirm` in Saleor.
3. Saleor ORDER_CONFIRMED → (potentially) back into Odoo → …

## Decision

We reuse the existing context flag **`saleor_sync_skip`** (already honored by every
outbound dispatcher: `_emit`/`_dispatch*` check
`records.env.context.get('saleor_sync_skip')`).

**Whenever order sync writes to Odoo in response to a Saleor event, it passes
`context={'saleor_sync_skip': True}`** in the JSON-2 call:

```python
await odoo.call("sale.order", "action_confirm", ids=[order_id],
                context={"saleor_sync_skip": True})
```

The server action for the order-status automation sees the flag in `env.context` →
`pass` (doesn't emit an event). The echo is broken at the very first link.

**Verified:** Odoo 19's JSON-2 API (`POST /json/2/{model}/{method}`) propagates the
`context` key into `env.context` (confirmed via a probe through
`default_get(default_note=...)`).

This is applied to the order-sync operations: `create` (draft), `action_confirm`,
`action_cancel`.

## Alternatives considered

- **Dedup on the middleware side** (remember "I triggered this state change
  myself"). Rejected: stateful, subject to races, more complex than the
  already-built-in context flag.
- **A separate technical user / marker field** on sale.order. Rejected: unnecessary
  schema; the context flag is clean and transactional (it only lives for the
  duration of the call).

## Consequences

**Pros:** zero new infrastructure (the flag already exists), fully
transaction-local, leaves no trace. Hardening test S4 confirms there's no echo.

**Cons:** depends on the `context` being propagated through JSON-2 (verified for
Odoo 19). If someone changes the state in Odoo **manually** (not triggered by
Saleor), the flag isn't set and the push happens as expected — that's the desired
behavior. The echo risk only exists for Saleor-initiated changes, where the flag is
set.
