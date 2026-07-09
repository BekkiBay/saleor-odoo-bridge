# ADR-0018: Reconcile cron, 02:00 UTC daily, dry-run by default

## Status
Accepted (2026-05-23)

## Context

Event-driven sync (ADR-0017) can miss an event: the middleware/worker could be down,
Redis could lose a job, or Odoo might fail to deliver a webhook. We need a safety
net that reconciles Odoo vs. Saleor stock levels and closes any drift. ADR-0010
originally called for reconciling every 5 minutes; in practice, for the MVP catalog
a daily reconciliation is enough, and a frequent bulk read puts unnecessary load on
both Odoo and Saleor.

## Decision

**A daily reconcile job at 02:00 UTC, dry-run by default (logs drift only).**

1. **An arq cron job** (`cron_jobs` in `WorkerSettings`): `reconcile_stock_drift`
   runs daily at 02:00 UTC, always in **dry-run** mode — it counts and logs
   `event=stock_reconcile_drift count=N`, without fixing anything.
2. **Auto-fix only manually**, via the CLI with an explicit flag:
   ```
   python -m saleor_bridge.cli.bulk_seed reconcile-stocks            # dry-run, exit 1 on drift
   python -m saleor_bridge.cli.bulk_seed reconcile-stocks --apply    # fixes the drift
   ```
   The operator reviews the log/table and applies the fix deliberately (see the
   `reconcile-procedure.md` runbook).
3. Drift is defined as `saleor_qty != MAX(odoo_raw - buffer, 0)` for a given
   (variant, warehouse) pair. A difference of exactly `buffer` is expected (the
   intended effect of ADR-0016), NOT drift.

`BRIDGE_STOCK_RECONCILE_INTERVAL` (env var, default 300) is kept around in case we
switch to an interval-based schedule later; for now the actual scheduler is the
daily arq cron.

## Alternatives considered

- **Auto-apply within the cron job.** Rejected: automatically fixing stock levels
  without a human in the loop is risky (a bug in the aggregation could cause a mass
  overwrite). Dry-run plus a manual `--apply` is safer for the MVP.
- **A system cron / Celery beat.** Rejected: arq is already in the stack;
  `cron_jobs` is ~5 lines of code, no need to pull in a new component.
- **Every 5 minutes (as in ADR-0010).** Relaxed to daily: less load, and
  event-driven sync already covers responsiveness — reconcile is a safety net, not
  the primary path.

## Consequences

**Pros:** an automatic daily drift detector with no risk of an unsupervised
auto-fix; a controlled manual apply; zero new components.

**Cons:** drift persists until the manual `--apply` or the next relevant event (but
it's visible in the log). As the catalog grows, the daily bulk read gets heavier —
tunable later if needed.
