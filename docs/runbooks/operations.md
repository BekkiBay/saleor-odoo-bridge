# Operations — Odoo ↔ Saleor catalog

Operational procedures for catalog sync. See also `bulk-seed.md`.

All CLI commands run inside the middleware container:
```bash
docker compose exec middleware python -m saleor_bridge.cli.bulk_seed <cmd>
```

## 1. Retry failed sync

When a binding went to `sync_state='failed'` (Saleor was unreachable, etc.):

```bash
# 1. list failed bindings
docker compose exec middleware python -c "
import asyncio,os
from saleor_bridge.odoo.client import OdooClient
async def m():
 o=OdooClient(url=os.environ['BRIDGE_ODOO_URL'],db=os.environ['BRIDGE_ODOO_DB'],api_key=os.environ['BRIDGE_ODOO_API_KEY'])
 print(await o.search_read('saleor.binding',[('sync_state','=','failed')],['model_name','odoo_id','error_message']))
asyncio.run(m())"

# 2. retry (outbound: product.template / product.category)
docker compose exec middleware python -m saleor_bridge.cli.bulk_seed retry-failed
```
`retry-failed` takes all `failed` bindings, re-runs the sync, and prints
`found/ok/failed/skipped`. Inbound records (res.partner/sale.order) are skipped.

This is also visible in Odoo under **Saleor Sync → Bindings** (Failed filter)
and **→ Outbox**.

## 2. Verify binding integrity (cron-able)

```bash
.venv/bin/python scripts/verify_bindings.py   # exit 0 ok, 1 = discrepancies found
```
Checks for orphan Odoo records / dead bindings / orphan Saleor records /
counts for products and catalog categories. For cron: run nightly, alert on
exit != 0.

Typical discrepancies and what to do:
| Finding | Action |
|---|---|
| orphan Odoo (product without a binding) | `retry-failed` or `bulk-seed` |
| dead binding (saleor_id no longer exists in Saleor) | `wipe` + `bulk-seed` (full reseed) |
| orphan Saleor (product without a binding) | delete it in Saleor manually, or `wipe`+`bulk-seed` |
| category count mismatch | check for parent-move divergence (see §4) |

## 3. Controlled archive / unarchive

Archiving a product in Odoo unpublishes it in Saleor (does not delete the product):
```bash
# UI: Inventory → Products → select → Action → Archive
# or via JSON-2:
docker compose exec -T odoo odoo shell -c /tmp/odoo.conf -d marketplace --no-http <<'PY'
env['product.template'].browse(<ID>).write({'active': False}); env.cr.commit()
PY
```
After ~5s in Saleor: `isPublished=false, isAvailableForPurchase=false`.
Unarchiving (`active=True`) publishes it again. The binding stays `synced`.

## 4. Category re-parent (LIMITATION)

⚠️ **The Saleor API does not support changing a category's parent**
(`CategoryInput` has no `parent`, and there's no move mutation). Renames sync
fine; **parent moves do not.**

What happens when you move a category in Odoo: the name updates, the parent
in Saleor stays the same, the binding goes to `sync_state='diverged'` with an
`error_message`, and the worker logs `category_parent_diverged`. Visible in
**Bindings** (Diverged filter).

To actually rebuild the category tree in Saleor:
```bash
docker compose exec middleware python -m saleor_bridge.cli.bulk_seed wipe --yes
docker compose exec middleware python -m saleor_bridge.cli.bulk_seed bulk-seed
```
(`wipe` clears both the Saleor catalog and the outbound bindings, so the
reseed rebuilds the tree from scratch.)

## 5. Full reset / reseed

```bash
docker compose exec middleware python -m saleor_bridge.cli.bulk_seed wipe --yes     # DESTRUCTIVE
docker compose exec middleware python -m saleor_bridge.cli.bulk_seed bulk-seed
.venv/bin/python scripts/verify_bindings.py
```
`wipe` deletes ALL Saleor products+categories and ALL outbound bindings
(product.template/category/type). Without clearing the bindings, a reseed
would try to update against dead ids.

## 6. Dedup and race conditions

- Webhooks are deduped in arq via `_job_id=odoo:<model>:<id>:<5s-bucket>` (+ `_defer_by=3`).
- Concurrent category creation is protected by a Redis lock
  `saleor_bridge:lock:product.category:<id>` plus a partial unique index
  `saleor_binding_model_odoo_uniq (model_name,odoo_id) WHERE odoo_id!=0`.

## 7. Known noise

During bulk operations in Odoo (or setup with the middleware down),
`saleor.outbox` accumulates `failed` rows and the automation fires multiple
times for the same record (no `trigger_field_ids` set). This does not break
sync (idempotent + dedup). Prune the outbox as needed; narrowing the trigger
fields is future work.
