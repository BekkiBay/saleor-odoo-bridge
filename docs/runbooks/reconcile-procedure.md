# Runbook — Stock reconcile procedure

Reconciling Odoo vs Saleor stock levels and closing drift. See ADR-0018 (and
ADR-0016 for the formula). Complements [stock-sync.md](stock-sync.md).

## What drift means

For each (variant, warehouse) pair:

```
expected = MAX(odoo_raw - BRIDGE_STOCK_SAFETY_BUFFER, 0)     # ADR-0016
drift    = saleor_qty != expected
```

A discrepancy of **exactly `buffer`** (e.g. Odoo=12, Saleor=11 with buffer=1)
is **expected**, NOT drift (it's just the safety buffer at work). Drift means
Saleor differs from `expected` (a lost event, a manual edit in Saleor, a bug).

## When to run it

- **Automatically:** an arq cron job every day at **02:00 UTC**, always
  **dry-run** — it only logs `event=stock_reconcile_drift count=N` (ADR-0018).
  It doesn't fix anything.
- **Manually:** after an incident (worker/Redis/Odoo was down), after bulk
  stock edits, or when you suspect the storefront is off.

## Dry run (default)

```bash
docker compose exec middleware python -m saleor_bridge.cli.bulk_seed reconcile-stocks
```

Prints a table and a summary. **Exit 0** = clean, **exit 1** = drift found.

```
        Stock reconcile (dry-run)
 SKU       Warehouse  Odoo  Saleor  Diff   Status
 SKU-001   wh-1       12    11      -1     (buffer — OK)
 SKU-005   wh-1       20    15      -5     ❌ DRIFT
checked=30 ok=29 drift=1 fixed=0
```

- `Odoo` — the raw aggregate (`odoo_raw`).
- `Saleor` — the current stock level in Saleor (summed across warehouses).
- `Diff` = `Saleor - Odoo` (`-buffer` when expected).
- `Status` — `(buffer — OK)` or `❌ DRIFT`.

## Apply (fix drift)

First look at the dry run and confirm the drift is real (not just the
expected buffer gap). Then:

```bash
docker compose exec middleware python -m saleor_bridge.cli.bulk_seed reconcile-stocks --apply
```

For each drifted SKU, sets `trackInventory=True` and pushes `expected`
(`MAX(odoo_raw - buffer, 0)`). **Exit 0** if every fix succeeded, **exit 1**
if at least one failed. After `--apply`, re-run the dry run — it should show
`drift=0`.

## Checking the cron job

```bash
# worker logs from overnight:
docker compose logs middleware-worker | grep stock_reconcile_drift
# manual run of the cron task (via arq) to test it:
docker compose exec middleware python -m saleor_bridge.cli.bulk_seed reconcile-stocks
```

> **Timezone:** the cron uses the container's clock (UTC by default for the
> python image). If the container has a different TZ set, adjust the hour in
> `cron(... hour=2 ...)` (`queue/arq_worker.py`), or set `TZ=UTC`.

## Escalation

- Drift on MANY SKUs at once → likely a systemic issue (warehouse↔channel,
  buffer mismatch, a whole batch of events lost). Don't run `--apply` blindly
  — investigate the cause first.
- `quantityAvailable=0` while `stocks.quantity>0` → the warehouse isn't in
  the channel's shipping zone (ADR-0015). `--apply` won't fix this — the
  warehouse needs to be attached to the channel.
