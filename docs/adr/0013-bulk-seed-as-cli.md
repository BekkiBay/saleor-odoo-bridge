# ADR-0013: Bulk seed as an idempotent CLI command, not a webhook flow

## Status
Accepted (2026-05-23)

## Context

The initial catalog export from Odoo to Saleor (18 categories + 30 products) is a
one-off operation. There are two ways to run it:

1. **Via the webhook flow** — make Odoo "fire" events for every record (e.g. a bulk
   `write`). Downsides: depends on Odoo itself initiating the export; adds noise to
   the outbox/logs; no control over ordering (categories must go before products);
   hard to support `--dry-run`.
2. **Via an explicit CLI command** — an operator triggers the export and can see the
   plan and progress.

## Decision

Bulk seed is a **separate, idempotent CLI command** (`typer`):

```bash
docker compose exec middleware python -m saleor_bridge.cli.bulk_seed bulk-seed
docker compose exec middleware python -m saleor_bridge.cli.bulk_seed bulk-seed --dry-run
docker compose exec middleware python -m saleor_bridge.cli.bulk_seed wipe   # tear down the Saleor catalog
```

- Order: ensure the ProductType exists → categories in **topological order** (parents
  before children) → products in batches.
- **Idempotency**: each `ensure_*` step first looks up `saleor.binding` by `odoo_id`;
  if found it updates, otherwise it creates. Re-running the command doesn't create
  duplicates.
- `--dry-run` prints the plan (how many creates/updates/skips) without mutating
  anything.
- Progress is rendered via `rich`.
- Doesn't depend on whether Odoo fires events: it reads the catalog from Odoo via
  JSON-2 and pushes it itself.

Ongoing changes (after the initial seed) go through the webhook flow
(`base.automation` → `/api/odoo-events` → arq), see ADR-0011.

## Alternatives considered

- **Webhook-based seeding (option 1).** Rejected: no control over ordering/plan,
  noisy, hard to support dry-run.
- **A management command inside Odoo (`odoo shell`).** Rejected: all the mapping
  logic and the Saleor client live in the middleware (ADR-0001); duplicating that in
  Odoo would be bad.

## Consequences

**Pros:** the operator explicitly triggers the run and sees the plan and progress;
topological ordering is under control; easy to repeat (idempotent) and to test.

**Cons:** one more entry point (the CLI) in the middleware image → one extra
dependency (`typer`). Acceptable.
