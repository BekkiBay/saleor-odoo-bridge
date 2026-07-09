# Runbook — Variants & Attributes Odoo ↔ Saleor

Syncs attributes (color/size/…) and variants from Odoo to the Saleor
storefront. Odoo is the source of truth. See ADR-0023..0027 (and
ADR-0007/0012 as the base).

## Architecture

```
Odoo product.attribute / .value  ──┐
   trigger(name, display_type / html_color)
                                   │
Odoo product.template (write)      │   ← attribute_line_ids change, list_price
   trigger(on_create_or_write)     │
                                   │
Odoo product.template.attribute.value (PTAV)
   trigger(price_extra) → emit product.template parent
                                   │
Odoo product.product (variant)     │
   trigger(default_code, barcode, active)
   + stock.quant(quantity) → product.product (see stock-sync.md)
                                   ▼
POST {middleware}/api/odoo-events?secret=…   {odoo_model, odoo_id, action}
   │ validate secret → enqueue arq (defer ~3s, dedup model+id+5s bucket) → 200
   ▼
arq worker: sync_odoo_record_to_saleor →
   • product.attribute[.value] → sync_attribute_to_saleor
       ensure Attribute (DROPDOWN/PRODUCT) + values + assign VARIANT to "Generic" (hasVariants=true)
   • product.template → sync_product_to_saleor + sync_template_variants_to_saleor
       reconciles the variant set (bulk create / adopt / delete) + prices
   • product.product → sync_variant_to_saleor (ensure variant + price + attrs) → sync_stock_to_saleor
```

**Important:**
- A single `product.product` event can come from TWO triggers (variant
  fields AND `stock.quant`). The dedup bucket ignores `action`, so the
  handler does both: ensures the variant, then syncs stock (ADR-0017).
  Idempotent, so a bucket collision is safe.
- `lst_price` on a variant is a **non-stored compute field** and can't be a
  trigger. Prices flow through `product.template` (list_price) and PTAV
  (`price_extra`) instead, ADR-0026.

## Preconditions

1. The catalog has been seeded and variants migrated (`bulk-seed-variants`).
2. The stack is up: `docker compose ps` → db, odoo, redis, middleware, middleware-worker.
3. The `saleor_sync` module is updated to v0.5 (variant/attribute automations):
   ```bash
   docker compose exec odoo odoo -d marketplace -u saleor_sync --stop-after-init
   docker compose restart odoo
   ```

## Operations

### Initial migration (existing single-variant → variant bindings)

```bash
docker compose exec middleware python -m saleor_bridge.cli.bulk_seed bulk-seed-variants
```
Adopts the dummy variants created during catalog seeding, creates
`saleor.binding(product.product)`. Idempotent — re-running is a no-op.
Expected: N templates → N variant bindings.

### Create an attribute with values (S1)

In Odoo: Inventory → Configuration → Attributes → New. Name it "Color", any
Display Type (it syncs as DROPDOWN, ADR-0027), `Variants Creation Mode` =
`Instantly` or `Dynamically` (NOT `Never` — `no_variant` gets skipped). Add
values Red/Blue/Green → Save. Webhook → Saleor Attribute + 3 values +
assigned to "Generic".

Verify:
```bash
# a "Color" attribute with 3 values should appear in Saleor
docker compose exec middleware python -c "import asyncio; ..."  # or verify_bindings.py
```

### Add variants to an existing product (S2)

In Odoo, on a `product.template`: Attributes & Variants tab → Add line →
Color [Red, Blue], Size [S, M, L] → Save. Odoo creates 6 `product.product`
records. Webhook (template + PTAV + product.product burst, collapsed by the
5s bucket) → reconciliation: the dummy variant is removed, 6 variants are
created (in bulk) with attribute assignments and the `list_price` price.

### Per-variant price surcharge (price_extra, S3)

In Odoo: on a PTAV (attribute line → a specific value, e.g. Size: L), set
`Extra Price` = 50000 → Save. Webhook (PTAV trigger → template event) →
reconciliation resets the variant price: Saleor variant "Size L" = list_price
+ 50000.

### Archive a variant (S4)

In Odoo: `product.product` → archive (active=False). Webhook → the variant
is deleted in Saleor (`productVariantDelete`, idempotent). Other variants
keep working.

## Pitfalls

- **Creation order in Saleor:** attribute → assign to ProductType → variant
  with the value. Sync attributes BEFORE variants, otherwise
  `AttributeBindingMissing` → arq retry (it converges on its own, but the
  first run may retry).
- **Variant SKUs:** Odoo does NOT generate `default_code` by default for
  auto-created variants. Set the SKU manually, otherwise it falls back to
  `odoo-<id>` (ADR-0024). SKUs must be globally unique.
- **Stock after a variant is recreated:** delete+create changes the Saleor
  variant ID → stock on the old ID disappears. Reconciliation triggers
  stock-sync for the new variants; if in doubt, run `bulk-seed-stocks`
  (ADR-0025).
- **Webhook bursts:** adding one attribute_line produces N PTAV + M
  product.product events. The 5s bucket dedups by (model, id). If you see
  >50 events for a single change, check whether the skip-guard is stuck in
  a loop.
- **`no_variant` attributes** (composition/material) — skipped (future work, ADR-0027).

## Verify

```bash
.venv/bin/python scripts/verify_bindings.py   # Products/Categories/Attributes/Variants
```
Attributes and Variants sections: orphan Odoo / dead binding / orphan Saleor / counts.
