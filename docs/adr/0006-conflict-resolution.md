# ADR-0006: Conflict resolution — Odoo always wins, divergence logged in chatter

## Status
Accepted (2026-05-21)

## Context

The source of truth for the catalog / stock / order statuses is Odoo.

The Saleor Dashboard still allows editing product fields (name, description, price). If an operator changes a product in Saleor, the next push from Odoo will overwrite that change. This can be:
- intentional (an admin fixed a typo, planning to carry it over to Odoo later);
- unintentional (the admin didn't know Saleor was read-only in practice);
- a legitimate emergency (Odoo is down, something needs an urgent fix).

We need a policy.

## Decision

**Odoo always wins** for all master entities: products, variants, categories, attributes, stock, prices.

When divergence is detected (the value in Saleor differs from Odoo at the next sync), the middleware **does not block the sync** — it performs the overwrite, but logs the event in two ways:

1. **A structlog WARNING** with `event=divergence`, `model=Product`, `saleor_id=...`, `odoo_value=...`, `saleor_value=...`.
2. **A post to the chatter** of the corresponding `product.template` / `sale.order` — a `mail.message` with body: `[Saleor sync] Divergence detected at {timestamp}: field '{name}' was '{saleor_value}' in Saleor, overwritten with '{odoo_value}' from Odoo.`

The operator sees the divergence history in the "Messages" tab on the product page in the Odoo UI. That's enough for a post-mortem without blocking business operations.

For **orders** and **customers** the policy is inverted: Saleor wins (the order originated on the storefront). Divergence here is only logged if a manual edit to `sale.order` appears in Odoo after `ORDER_CREATED` (a rare case).

## Alternatives considered

1. **Bidirectional sync with conflict markers.** Like git merge conflicts. **Rejected:** there's no UI for an operator to resolve conflicts. Too complex.

2. **Read-only Saleor admin for the catalog.** Remove `MANAGE_PRODUCTS` from staff users via Saleor permissions. **Rejected:** we want to keep a manual override option for emergency fixes. Removing the permission would remove that fallback.

3. **Stop syncing on divergence, alert an admin.** **Rejected:** a single divergence would block ALL updates to that product. Too fragile.

## Consequences

**Pros:**
- Simple mental model: "Saleor is a window into Odoo."
- No sync stalls — the overwrite always goes through.
- Audit trail in the chatter.

**Cons:**
- If an admin edits Saleor and doesn't notice the overwrite, the change is lost.
- The chatter can get cluttered with messages from frequent edits made "in the wrong system."

**Mitigation:**
- A Slack alert (channel `#saleor-sync-divergence`) on any divergence event — the admin sees it immediately.
- A future dashboard view: "divergence in the last 24h" filterable by model.

## Addendum (hardening pass, 2026-05-23)

**Divergence handling implemented for the product name:** on update, `sync_product` reads
the current Saleor `name` plus `metafields['odoo_synced_name']`; on a manual edit in Saleor
it posts to the `product.template` chatter (`message_post`) and overwrites. Verified live.

**Category parent-move — a divergence that CANNOT be resolved by overwrite.**
The Saleor API cannot change a category's parent (`CategoryInput` has no `parent`, and there
is no move mutation — confirmed by introspection). So when `parent_id` changes in Odoo,
"Odoo wins" doesn't apply. Behavior: `sync_category` detects the parent mismatch (Saleor vs.
desired), logs `log.warning('category_parent_diverged')`, and marks
`saleor.binding.sync_state='diverged'` plus `error_message` (visible in the Bindings
dashboard, filterable by "Diverged"). The name still syncs normally. A full re-parent
requires `wipe` + `bulk-seed` (see `operations.md` §4). `product.category` has no
mail.thread, so chatter isn't available there — divergence is reflected on the binding
instead.

**Layer clarification (failed sync):** a failure on the Saleor side of the sync shows up in
`saleor.binding.sync_state='failed'`, NOT in `saleor.outbox` (the outbox audits the
Odoo→middleware hop, which still returns `confirmed/200` even if the subsequent Saleor call
fails).
