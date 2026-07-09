# Runbook — Stock sync Odoo → Saleor

Syncs stock levels from Odoo (`stock.quant`) to the Saleor storefront. Odoo
is the source of truth for stock. See ADR-0015..0018 (and ADR-0010 as the base).

## Architecture

```
Odoo stock.quant (quantity write)
   │ base.automation (trigger_field=quantity) → ir.actions.server (code)
   │ records._saleor_dispatch_stock(): saleor.outbox + POST per product.product
   ▼
POST {middleware}/api/odoo-events?secret=…   {odoo_model:'product.product', odoo_id:N, action:'write'}
   │ validate secret → enqueue arq (defer ~3s, dedup model+id+5s bucket) → 200
   ▼
arq worker: sync_odoo_record_to_saleor → product.product branch → sync_stock_to_saleor
   1. product.product → product_tmpl_id → saleor.binding(product.template) → Saleor product
   2. Saleor product → variants[0].id
   3. ensure_warehouse (get-or-create, ADR-0015)
   4. aggregate internal quants + safety buffer (ADR-0016)
   5. trackInventory=True + productVariantStocksUpdate
   6. touch saleor.binding.last_sync_out
```

**Important:** the event subject is `product.product`, not the quant itself.
The worker re-reads the current stock aggregate from Odoo (resilient to
races and deleted quants, ADR-0017).

## Preconditions

1. The catalog has already been seeded: `bulk-seed` has run, and products
   have a `saleor.binding(product.template)`. Without a catalog binding,
   stock-sync for that product raises `CatalogBindingMissing` → arq retry →
   if the catalog is never seeded, it ends up `failed`.
2. The stack is up (`docker compose ps` → db, odoo, redis, middleware, middleware-worker).
3. The `saleor_sync` module is updated to v0.3 (includes the stock automation):
   ```bash
   docker compose exec odoo odoo -d marketplace -u saleor_sync --stop-after-init
   docker compose restart odoo
   ```

## Initial stock export

```bash
docker compose exec middleware python -m saleor_bridge.cli.bulk_seed bulk-seed-stocks
```
Idempotent (`productVariantStocksUpdate` = upsert). Output is a
`Total / Synced / Skip / Failed` table. `Skip` = variants without a catalog
binding (not in the Saleor catalog) — this is expected. Exit 1 if `Failed > 0`.

## Incremental sync (automatic)

Change a stock level in Odoo (Inventory → Adjustments / validating a
picking) → after ~5s Saleor shows `MAX(qty - buffer, 0)`. Verify with:

```graphql
query { productVariant(id:"<VARIANT_ID>"){ sku trackInventory quantityAvailable
  stocks{ quantity warehouse{ slug } } } }
```

## Safety buffer (ADR-0016)

`BRIDGE_STOCK_SAFETY_BUFFER` (env var, default 1). Saleor gets
`MAX(raw - buffer, 0)`. So Saleor is always `buffer` lower than Odoo — this
is **expected**, not drift. Changing the buffer:
```bash
# .env → BRIDGE_STOCK_SAFETY_BUFFER=2, then (NOT restart — it doesn't reread env):
docker compose up -d middleware middleware-worker
docker compose exec middleware python -m saleor_bridge.cli.bulk_seed bulk-seed-stocks
```

## Troubleshooting

| Symptom | Cause | Action |
|---------|---------|----------|
| Product shows "out of stock" with nonzero quantity | buffer consumed the stock (raw ≤ buffer) or stock hasn't been seeded | `bulk-seed-stocks`; check `quantityAvailable` |
| Stock not updating | automation didn't fire / event never arrived | `saleor.outbox` (Odoo) — is there a record? worker logs show `stock_synced`? |
| `quantityAvailable=0` even though `stocks.quantity>0` | warehouse not attached to the channel | see ADR-0015 (reuse the default warehouse), `reconcile-stocks` |
| Worker logs `CatalogBindingMissing` | catalog not yet synced for the product | `bulk-seed` (catalog) → then `bulk-seed-stocks` |
| Odoo vs Saleor drift | a lost event | `reconcile-stocks` (see [reconcile-procedure.md](reconcile-procedure.md)) |

## Known limitations

- **Single warehouse** (ADR-0015): multiple Odoo warehouses collapse into a
  single Saleor warehouse.
- **Reservations are independent**: Odoo's `reserved_quantity` (picking) and
  Saleor's reservation (checkout) are two independent systems. This stock
  sync does NOT sync them. It only pushes on-hand `quantity`; Saleor's
  `quantityReserved` is left untouched.
- **`trackInventory`** is flipped to `True` on a variant's first stock sync
  (needed so "out of stock" shows at 0). Before that it was `False`.
