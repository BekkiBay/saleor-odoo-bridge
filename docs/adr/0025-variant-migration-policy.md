# ADR-0025: Migration policy for existing single-variant products

## Status
Accepted (2026-05-23). Closes out the debt noted in ADR-0012.

## Context

After the initial catalog sync, Saleor has 30 products, each with a single dummy
`ProductVariant` (SKU = `template.default_code`, ADR-0012). Bindings only exist at
the `product.template` level; there are NO bindings at the `product.product`
(variant) level. This decision introduces per-variant bindings and multi-variant
support. We can't break the 30 live products or any active orders (SKU is stable,
per ADR-0024).

## Decision

An authoritative reconciliation of the variant set
(`sync_template_variants_to_saleor`): desired (the template's active
`product.product` records) vs. current (Saleor variants), diffed by SKU.

1. **Single variant, no attributes** → desired = [1 variant, SKU = template SKU] =
   current (the dummy). SKU match → **adopt**: create a binding from
   `product.product` to the existing dummy variant. Saleor is NOT changed. The price
   is re-applied (idempotent).
2. **The template gains attributes** → Odoo recreates its `product.product` records
   (new SKUs). desired = the new variants, current = the old dummy. The dummy SKU
   is not in desired → **delete** the dummy; the new variants are **bulk created**
   with their attribute assignments.
3. **Initial migration** — the `bulk-seed-variants` CLI command runs the
   reconciliation across every synced template: the 30 single-variant products get
   variant bindings.
4. **Self-healing** — even without running the CLI, the very first event on a
   `product.product` (an edit or stock change) adopts the dummy and creates the
   binding.

## Alternatives considered

- **Wipe and re-seed the whole catalog.** Rejected: breaks active orders and URLs,
  and changes every Saleor ID unnecessarily.
- **A per-variant unlink trigger to remove the dummy.** Fragile: when Odoo
  regenerates variants, it archives/unlinks them unpredictably. Reconciling per
  template is more reliable (a single authoritative diff).

## Consequences

**Pros:** zero-downtime migration; idempotent; SKUs and orders aren't broken;
self-healing covers a missed CLI run.

**Cons:** on the single→multi transition, the dummy is recreated (delete+create) →
a new variant ID, and its stock disappears → a **stock resync** is needed after
recreation (stock is tied to the variant_id). The reconciliation triggers stock sync
for the new variants through the standard `product.product` flow.
