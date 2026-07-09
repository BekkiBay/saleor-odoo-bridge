# ADR-0008: Failed sync — Slack alert + email + admin dashboard, manual intervention

## Status
Accepted (2026-05-21)

## Context

A webhook arrives from Saleor, signature verification passes, but the sync business logic fails: Odoo returns a 5xx, a PG deadlock occurs, a ValidationError is raised (SKU not found), a Saleor mutation gets rate-limited, etc.

The canonical pattern is `queue_job` with `max_retries=5` and exponential backoff. After 5 attempts, the job moves to `failed` state. What happens next?

Options:
- **Auto-cancel the order + refund the customer.** Good for UX, bad if the problem is transient (e.g., Odoo down for 10 minutes).
- **Email the customer "there was a problem processing your order."** Could be alarming.
- **Stay silent and let an admin discover it via a cron job.** The "we find out a week later" scenario.

We settled on: **alert + manual intervention**.

## Decision

After 5 retries, a `queue_job` job moves to `failed` state:

1. **Slack alert** to the `#saleor-sync-failed` channel (URL in env `BRIDGE_SLACK_WEBHOOK_URL`, optional). Payload: event_type, saleor_id, error_message, a link to the admin dashboard.
2. **Email** to `ops@example.com` (address configurable via env `BRIDGE_OPS_EMAIL`). Same content.
3. **Admin dashboard** in Odoo: a `saleor.binding` tree view filtered by `sync_state='failed'`, plus a stand-alone `Failed Jobs` view (via the `queue.job` model).
4. **No automatic refund / cancel** — the operator decides manually: retry, fix the data, cancel the order, etc.
5. **Customer not notified** — if the sync fails downstream, the customer already sees "order placed" in Saleor. This is resolved in minutes, not hours.

`saleor.binding.sync_state` has a `failed` value plus an `error_message` text field for diagnostics.

## Alternatives considered

1. **Retry indefinitely.** **Rejected:** an infinite loop on a permanent failure (e.g., SKU genuinely missing). Better to fail fast and alert.

2. **Auto-cancel the order after 24 hours.** **Rejected:** we want manual control here — there can be legitimate reasons for a delay.

3. **Customer-facing notification.** **Rejected:** noise. Most failed syncs resolve within 30 minutes.

## Consequences

**Pros:**
- A clear escalation path.
- The operator controls the situation (refund / fix / retry).
- Audit trail in `saleor.binding.error_message`.

**Cons:**
- Requires a human on call (at least during business hours).
- Slack + email is double notification noise.
- Early on, there will be a lot of false alerts until edge cases are ironed out.

**Mitigation:**
- A future iteration could add a **retry button** directly in the Odoo UI — the operator clicks it and the job runs again.
- A future iteration could add alert rate-limiting (dedup by `(event_type, saleor_id)` over an hour).
- Slack and email can both be disabled via env vars (for dev, usually neither is configured).

**The alert pipeline itself is not implemented yet** — it will be built once the first real sync flow goes live. For now, this ADR fixes the policy.
