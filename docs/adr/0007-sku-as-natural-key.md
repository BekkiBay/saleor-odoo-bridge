# ADR-0007: SKU as the natural key, with Odoo ID as a mapping-table fallback

## Status
Accepted (2026-05-21)

## Context

When processing a Saleor `OrderLine`, we need to find the corresponding `product.product` in Odoo. Two options:

1. **By SKU:** `product.product.default_code == OrderLine.productSku`. Human-readable, survives migrations, but `default_code` isn't unique by SQL constraint (only unique by convention).
2. **By internal ID via a mapping table:** look up `saleor.binding` where `saleor_id == OrderLine.variant.id`.

The initial catalog (30 products from an xlsx import) all have SKUs of the form `SKU-001..030`. They're validated as unique at import time via `lib/products.py`. Future imports also go through SKU. Saleor's `ProductVariant.sku` is a required field, and we always populate it.

## Decision

**Primary key for resolving a product variant: SKU.**

```python
def resolve_variant(saleor_sku: str, saleor_id: str) -> int | None:
    Tmpl = env['product.product']
    # 1. Try SKU
    ids = Tmpl.search([('default_code', '=', saleor_sku)], limit=2)
    if len(ids) == 1:
        return ids[0]
    if len(ids) > 1:
        log.warning("SKU collision in Odoo", sku=saleor_sku, ids=ids)
        # fall through to mapping
    # 2. Try mapping table
    binding = env['saleor.binding'].search([
        ('model_name', '=', 'product.product'),
        ('saleor_id', '=', saleor_id),
    ], limit=1)
    if binding:
        return binding.odoo_id
    return None
```

**When a binding is created**, we populate both: the SKU and the `saleor.binding` row. SKU is for the fast happy-path lookup; the mapping is for edge cases (SKU collision, SKU change, manual data fixes).

**SKU collision policy:** if 2+ `product.product` records in Odoo end up with the same `default_code`, that's a data quality bug. We log a WARNING, send a Slack alert, and fall back to the mapping. We don't fail the sync.

## Alternatives considered

1. **Only the mapping table, ignore SKU.** **Rejected:** the mapping is an indexed read on every lookup anyway. SKU search uses the same kind of index (`default_code` is indexed), but it's simpler for human debugging ("find me product X in both systems").

2. **Only SKU, no mapping.** **Rejected:** if the SKU is lost, the whole sync breaks. The mapping is a safety net.

3. **Composite key (SKU + barcode + name).** **Rejected:** YAGNI. Added complexity without business value.

## Consequences

**Pros:**
- Fast happy-path lookup (SKU index).
- Survives Odoo migrations (XMLIDs can shift on import/export, SKU doesn't).
- Human-debuggable: an operator can see the SKU in both systems.

**Cons:**
- SKU is mutable in Odoo — if an operator changes `default_code`, sync breaks until the mapping is fixed manually.
- SKU collisions (two products with the same `default_code`) are a data bug requiring human intervention.

**Mitigation:**
- Add a SQL constraint in the `saleor_sync` Odoo module: **`unique(default_code) WHERE active=true`** (a follow-up task, not part of the initial scaffold). This enforces uniqueness for new data.
- When a SKU change in Odoo is observed (via `base.automation` on `product.product` write), auto-update `saleor.binding.last_sync_*` and trigger a re-sync.
