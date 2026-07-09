# ADR-0026: Per-variant, per-channel pricing (price_extra propagation)

## Status
Accepted (2026-05-23)

## Context

In Odoo, a variant's price = `template.list_price` + the sum of the `price_extra`
values from the PTAVs (product.template.attribute.value) that apply to that
variant. The computed result lives in `product.product.lst_price`. In Saleor, price
lives in `ProductVariantChannelListing` per (variant, channel) (per ADR-0004, a
single channel for the MVP).

The trigger problem: `lst_price` on `product.product` is a **non-stored compute**
field (confirmed by introspection). `base.automation` can't trigger on a non-stored
field. So a variant price change can't be caught directly on the variant.

## Decision

- **The source for a variant's price is `lst_price`** (we read the already-computed
  value; we don't sum `price_extra` ourselves).
  `domain.Variant.price = product.product.lst_price`.
- **Push to `ProductVariantChannelListing`** via `productVariantChannelListingUpdate`
  (single update) or inline `channelListings` in `productVariantBulkCreate`.
- **Price triggers live on the sources, not on `lst_price`:**
  - a `product.template` write (including `list_price`) → the template handler
    reconciles the prices of all its variants;
  - `product.template.attribute.value.price_extra` (which is stored!) → we emit an
    event for the parent `product.template` → the same reconciliation runs.
- The worker reads a fresh `lst_price` from Odoo (after commit, with a 3s defer) —
  by then it's already recomputed as `list_price + price_extra`.

## Alternatives considered

- **Trigger on `product.product.lst_price`.** Not possible: the field is a
  non-stored compute.
- **Sum `list_price + price_extra` in the middleware.** Duplicates Odoo's logic,
  with a risk of drift under complex pricelist rules. `lst_price` is the single
  source of truth.
- **Trigger on `product.product` for price changes.** Wouldn't fire: writing
  `price_extra` on a PTAV doesn't write to `product.product`.

## Consequences

**Pros:** price is always consistent with Odoo (we read `lst_price`); both change
paths (list_price and price_extra) are covered; reconcile re-applies prices
idempotently.

**Cons:** editing a single PTAV's `price_extra` reconciles ALL variants of the
template, not just the affected ones. For a catalog with a small attribute set
(e.g., a handful of sizes × a handful of colors), this overhead is negligible. More
targeted, fine-grained reconciliation can be added later if needed.
