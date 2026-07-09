# ADR-0012: A single Saleor ProductType "Generic" for the whole catalog

## Status
Accepted (2026-05-23)

## Context

In Odoo, the initial catalog is 30 **simple products** (`product.template` with no
variants/attributes). In Saleor, a product must have a `ProductType` and at least one
`ProductVariant` (price and SKU live on the variant, not the product).

A full mapping of Odoo attributes/values to Saleor variant attributes is a
significant follow-up piece of work. It isn't needed yet and would only add
unnecessary complexity right now.

## Decision

- **A single `ProductType` "Generic"** for the whole catalog. The name comes from
  `BRIDGE_SALEOR_PRODUCT_TYPE_NAME` (default `Generic`). It's created via
  get-or-create, with the ID cached in `saleor.binding`
  (`model_name='product.type'`, `odoo_id=0`).
- Created **without variant attributes** and without product attributes, so a
  product can have a single "empty" variant.
- Each Odoo `product.template` maps to one Saleor `Product` plus **one dummy
  `ProductVariant`** sharing the same SKU (`default_code`). Price and the channel
  listing live on that variant.
- `kind = NORMAL`, `isShippingRequired = true`, `hasVariants = false`.

## Alternatives considered

- **A ProductType per Odoo category.** Rejected: YAGNI, adds mapping complexity
  without business value at this stage. The category is already expressed via
  Saleor's `Category`.
- **Configurable products (variants) right away.** Rejected: that's a later piece of
  work; Odoo doesn't yet have variants to sync.

## Consequences

**Pros:** a simple, predictable 1 product → 1 product + 1 variant mapping. Easy to
change price/SKU. A single type means no overhead for managing multiple types.

**Cons:** once real variants are introduced, products created as single-variant
"Generic" products will need to be migrated to types with attributes (the variant ID
changes, requiring a re-mapped binding). This is a known, deliberately deferred piece
of debt.

**Supersedes hint:** when variants are introduced, a follow-up ADR "ProductType per
attribute-set" should reference `Supersedes ADR-0012`.
