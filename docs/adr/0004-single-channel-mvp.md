# ADR-0004: Single channel `default-channel` for the MVP

## Status
Accepted (2026-05-21)

## Context

Saleor models a multi-storefront setup through `Channel` — each channel has its own currency, language, country, and pricelist (`ProductVariantChannelListing.price`).

Right now we have exactly one: `default-channel`, using the channel currency, with UI support for two languages. The current deployment targets a single B2C market; wholesale (B2B) and any additional storefront are out of scope for now.

Full multi-channel support in the sync layer means N iterations of `productVariantChannelListingUpdate` per product update, plus N pricelists in Odoo and N mapping records. That's roughly +30% code complexity and +50% testing time.

## Decision

**For now — only one channel: `default-channel`.**

Concretely, this means:
- Product sync creates exactly one `ProductChannelListing` and exactly one `ProductVariantChannelListing` per variant.
- Price is taken from `product.template.list_price` (no pricelist lookup).
- Orders are filtered by `channel.slug = 'default-channel'`.
- `saleor.binding` has no `channel_id` column.

Multi-channel support is a separate future ADR (once a wholesale or additional storefront channel is needed). The migration will be non-breaking: we'll add a `channel_id` field to `saleor.binding` defaulting to the current channel, and backfill it for existing records.

## Alternatives considered

1. **Build a multi-channel-ready schema from day one.** **Rejected:** YAGNI. Would add complexity to the order/catalog/stock/variant sync work without any business benefit right now.

2. **One Saleor instance, two warehouses as a proxy for multi-region.** **Rejected:** a warehouse is not a channel in Saleor. Multi-region pricing still requires a channel.

## Consequences

**Pros:**
- Simpler sync code (~30% fewer LOC).
- Fewer edge cases (no per-channel price override conflicts).
- Faster to deliver the MVP.

**Cons:**
- When an additional channel is needed, there will be a one-time migration (schema + data).
- Hardcoded `channel.slug == 'default-channel'` in a few places will need to be cleaned up.

**Mitigation:** all hardcoded references to `'default-channel'` in the middleware code go through `Settings.saleor_default_channel: str = 'default-channel'`. Future cleanup is `grep -r saleor_default_channel` + replacing it with a per-call parameter.
