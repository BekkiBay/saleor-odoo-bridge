# ADR-0024: Variant SKU = product.product.default_code

## Status
Accepted (2026-05-23). Extends ADR-0007 to the variant level.

## Context

ADR-0007 established SKU (`default_code`) as the natural key between Odoo and
Saleor at the product level. This decision brings that key down to the variant
level: each `product.product` maps to one Saleor `ProductVariant`. Saleor requires
SKU to be **globally unique** (not just unique per product). Order resolution (see
ADR-0007) already relies on `product.product.default_code`.

## Decision

- **`ProductVariant.sku = product.product.default_code`.** This is the single
  natural key used for resolving a variant, diffing the variant set, and carrying
  stock over when variants are recreated.
- If `default_code` is empty, **fall back to `odoo-<product.product.id>`** (as with
  products in ADR-0007). Globally unique and stable.
- The operator sets variant SKUs manually, or Odoo auto-generates them from a
  template (e.g. `TEMPLATE-S-RED`). We don't enforce a template — we just read
  whatever is there.
- Reconciling the variant set (`sync_template_variants_to_saleor`) matches desired
  (Odoo) against current (Saleor) **by SKU**: a match means adopt/update, a new SKU
  means create (in bulk), and a SKU no longer present means delete.

## Alternatives considered

- **Odoo variant id as the key, via metadata.** Rejected: SKU is already needed and
  is already the natural key for orders; a second key would be redundant.
- **A composite key (template SKU + attribute combination).** Fragile: renaming an
  attribute would break the key; SKU is more stable.

## Consequences

**Pros:** a single key for everything (catalog, variants, stock, orders); the
single-variant migration is transparent (dummy SKU = template SKU = product.product
SKU).

**Cons:** a SKU collision between two `product.product` records means one
overwrites the other in Saleor. Mitigated by the fallback guaranteeing uniqueness;
on a manual duplicate, we log a `sku_collision` event (as in order resolution).
Keeping SKUs unique is the responsibility of the Odoo operator.
