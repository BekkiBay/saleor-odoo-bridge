# Architecture Decisions — Index

Quick-reference index of all ADRs. Every ADR is append-only. Changing a decision means writing a new ADR with a `Superseded by` reference in the `Status` of the old one.

| #    | Title                                                                  | Status                | Date       |
|------|--------------------------------------------------------------------------------------------------|-----------|------------|
| 0001 | [Python middleware (not TypeScript)](adr/0001-python-middleware.md)    | Accepted              | 2026-05-21 |
| 0002 | [No Saleor App SDK — thin custom impl](adr/0002-no-saleor-app-sdk.md)  | Accepted              | 2026-05-21 |
| 0003 | [Odoo custom module `saleor_sync`](adr/0003-odoo-custom-module.md)     | Accepted              | 2026-05-21 |
| 0004 | [Single channel `default-channel` MVP](adr/0004-single-channel-mvp.md) | Accepted        | 2026-05-21 |
| 0005 | [Order flow: created→draft, paid→confirm](adr/0005-order-flow.md)      | Accepted              | 2026-05-21 |
| 0006 | [Conflict resolution: Odoo wins, divergence in chatter](adr/0006-conflict-resolution.md) | Accepted | 2026-05-21 |
| 0007 | [SKU as natural key + mapping fallback](adr/0007-sku-as-natural-key.md) | Accepted             | 2026-05-21 |
| 0008 | [Failed sync: Slack + email + admin dashboard](adr/0008-failed-sync-handling.md) | Accepted     | 2026-05-21 |
| 0009 | [Refunds deferred](adr/0009-refunds-deferred.md)            | Accepted              | 2026-05-21 |
| 0010 | [Stock consistency: safety buffer + reconcile cron](adr/0010-stock-consistency.md) | Accepted   | 2026-05-21 |
| 0011 | [Secret in query for Odoo→middleware webhook](adr/0011-secret-in-query-for-odoo-webhook.md) | Accepted | 2026-05-23 |
| 0012 | [Single ProductType "Generic" for the MVP catalog](adr/0012-single-product-type-mvp.md) | Accepted | 2026-05-23 |
| 0013 | [Bulk seed as an idempotent CLI command](adr/0013-bulk-seed-as-cli.md) | Accepted | 2026-05-23 |
| 0014 | [Stock out of scope for catalog sync](adr/0014-stock-out-of-scope-3-2.md) | Accepted | 2026-05-23 |
| 0015 | [Single-warehouse MVP (1 Odoo → 1 Saleor)](adr/0015-single-warehouse-mvp.md) | Accepted | 2026-05-23 |
| 0016 | [Safety buffer MAX(qty - buffer, 0)](adr/0016-safety-buffer-policy.md) | Accepted | 2026-05-23 |
| 0017 | [Stock trigger = stock.quant write (quantity)](adr/0017-stock-quant-trigger.md) | Accepted | 2026-05-23 |
| 0018 | [Reconcile cron 02:00 UTC daily, dry-run](adr/0018-reconcile-cron.md) | Accepted | 2026-05-23 |
| 0019 | [Order status mapping Odoo → Saleor](adr/0019-order-status-mapping.md) | Accepted | 2026-05-23 |
| 0020 | [Reverse-echo prevention via skip-guard context](adr/0020-skip-guard-mechanism.md) | Accepted | 2026-05-23 |
| 0021 | [Single full fulfillment per order (MVP)](adr/0021-single-fulfillment-mvp.md) | Accepted | 2026-05-23 |
| 0022 | [Customer notification policy](adr/0022-notification-policy.md) | Accepted | 2026-05-23 |
| 0023 | [Single "Generic" ProductType with variant attributes](adr/0023-product-type-strategy.md) | Accepted | 2026-05-23 |
| 0024 | [Variant SKU = product.product.default_code](adr/0024-variant-sku-natural-key.md) | Accepted | 2026-05-23 |
| 0025 | [Migration policy for single-variant products](adr/0025-variant-migration-policy.md) | Accepted | 2026-05-23 |
| 0026 | [Per-variant per-channel pricing (price_extra)](adr/0026-per-variant-channel-pricing.md) | Accepted | 2026-05-23 |
| 0027 | [Attribute input type DROPDOWN only (MVP)](adr/0027-attribute-dropdown-only-mvp.md) | Accepted | 2026-05-23 |

See also:
- [ADR README](adr/README.md) — format and process.
