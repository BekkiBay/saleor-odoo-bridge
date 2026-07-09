# ADR-0009: Refunds deferred, out of MVP scope

## Status
Accepted (2026-05-21)

## Context

The initial MVP scope covers: Saleor → Odoo order and customer sync, Odoo → Saleor catalog sync, stock sync, order-status sync (Odoo → Saleor), and variants + attributes.

Refunds were initially planned as part of that scope but the decision was made to leave them out for now. Reasoning: the store's return rate is expected to be low in the early months, and a full refund schema (partial refund + stock return + invoice reversal) adds 12+ hours of work and complex edge cases (chargebacks, exchange vs. refund) that are better designed once real return-pattern data is available.

## Decision

**Refunds are not implemented in this iteration.**

Concretely:
- The `ORDER_REFUNDED` / `ORDER_FULLY_REFUNDED` webhooks — **not subscribed to** in the manifest.
- Mapping for `account.move` (`out_refund`) / `account.payment` (outbound) — not written.
- Reverse stock picking — not written.

`ORDER_CANCELLED` (a full cancel before fulfillment) **is** handled (see ADR-0005) — that's not a refund in the financial sense, it's `_action_cancel()` on the sale.order, which releases reserved stock without touching money.

**Schema requirement:** the design of `saleor.binding` and the mapping table must **allow refunds to be added later without breaking changes**.

Concretely:
- `saleor.binding.model_name` is already generic — `account.payment`, `account.move`, and `stock.return.picking` records can be added later.
- `saleor.binding.saleor_id` stores a base64 ID — `TransactionItem.id` fits there without any schema change.
- The `sync_state` Selection already includes `synced`, `failed`, `diverged` — `refunded` can be added without a migration (extending a Selection in Odoo is idempotent).

## Alternatives considered

1. **Implement a "minimal refund" — full refund only.** **Rejected:** in practice, partial refunds account for roughly 80% of returns. A half-feature is worse than no feature.

2. **Implement the storage schema for refunds without any logic.** Stub fields + DB schema, no automation. **Rejected:** YAGNI. The schema will likely change once the real logic is built anyway.

## Consequences

**Pros:**
- 12 fewer hours of work → faster delivery of the MVP.
- Fewer edge cases to cover during testing.
- Real return patterns will accumulate over 2-3 months, enabling a better refund-flow design later.

**Cons:**
- A manual workflow is needed for refunds in the meantime:
  - Refund manually in the payment provider's dashboard.
  - Cancel the order in the Saleor Dashboard.
  - Reverse the stock in Odoo manually (`Inventory → Adjustments`).
- This manual process needs to be documented in a runbook.

**Mitigation:**
- A step-by-step operator runbook for manual refunds should be written separately.
- A later iteration could add a `saleor_sync.refund` model plus an automated flow. Historical refunds could be backfilled via a separate cron job driven by `ORDER_REFUNDED` events from Saleor's history (which Saleor retains).
