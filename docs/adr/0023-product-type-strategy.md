# ADR-0023: Single "Generic" ProductType with variant attributes

## Status
Accepted (2026-05-23). Extends ADR-0012.

## Context

ADR-0012 introduced a single ProductType "Generic" (`hasVariants=false`, no
attributes) for the 30 single-variant products. This decision introduces real
variants: size × color × material. In Saleor, attributes live on the ProductType,
and variants select values from those attributes.

The question: should the catalog be split into multiple ProductTypes (one per
product category, say), each with its own attribute set, or should everything stay
on a single type?

## Decision

- **A single ProductType "Generic"** for the whole catalog (as in ADR-0012), but now
  with `hasVariants=true` and all the variant attributes attached.
- All `product.attribute` records from Odoo are synced as **VARIANT attributes** of
  this single type (`productAttributeAssign(type: VARIANT, variantSelection: true)`).
- `hasVariants` is flipped lazily in `ensure_product_type_has_variants` the first
  time an attribute is synced (idempotent).

## Alternatives considered

- **A ProductType per category/product class.** Rejected: Odoo doesn't model a
  "product class" separately from category; the type would have to be derived
  heuristically. This complicates the binding (a per-type ID is needed) and the
  migration. There's no business value in this for the MVP — the storefront renders
  a single attribute set regardless.
- **Attribute at the product level instead of the variant level.** Doesn't fit:
  size/color determine the variant specifically (price, SKU, stock), not the
  product.

## Consequences

**Pros:** a simple mapping from `product.attribute` to a single type; no need to
resolve a type per product; migrating from single→multi variant doesn't change the
ProductType.

**Cons:** Saleor renders ALL variant attributes for every product of type
"Generic" (e.g., the operator in the admin panel sees both a Size and a Shoe Size
attribute on a product that only needs one). This isn't a problem for the storefront
(only attributes with real variant values are shown). If strict differentiation is
ever needed, a future split with `Supersedes ADR-0023` can address it.

**Trade-off:** less flexibility in exchange for simplicity — a deliberate MVP
choice.
