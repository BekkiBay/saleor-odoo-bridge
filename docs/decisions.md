# Architecture Decisions — Index

Quick reference индекс всех ADR'ов. Каждый ADR — append-only. Изменение решения = новый ADR со ссылкой `Superseded by` в `Status` старого.

| #    | Title                                                                  | Status                | Phase | Date       |
|------|------------------------------------------------------------------------|-----------------------|-------|------------|
| 0001 | [Python middleware (not TypeScript)](adr/0001-python-middleware.md)    | Accepted              | 3.0   | 2026-05-21 |
| 0002 | [No Saleor App SDK — thin custom impl](adr/0002-no-saleor-app-sdk.md)  | Accepted              | 3.0   | 2026-05-21 |
| 0003 | [Odoo custom module `saleor_sync`](adr/0003-odoo-custom-module.md)     | Accepted              | 3.0   | 2026-05-21 |
| 0004 | [Single channel `default-channel` (UZS) MVP](adr/0004-single-channel-mvp.md) | Accepted        | 3.0   | 2026-05-21 |
| 0005 | [Order flow: created→draft, paid→confirm](adr/0005-order-flow.md)      | Accepted              | 3.1   | 2026-05-21 |
| 0006 | [Conflict resolution: Odoo wins, divergence in chatter](adr/0006-conflict-resolution.md) | Accepted | 3.2   | 2026-05-21 |
| 0007 | [SKU as natural key + mapping fallback](adr/0007-sku-as-natural-key.md) | Accepted             | 3.1   | 2026-05-21 |
| 0008 | [Failed sync: Slack + email + admin dashboard](adr/0008-failed-sync-handling.md) | Accepted     | 3.1   | 2026-05-21 |
| 0009 | [Refunds deferred to Phase 4](adr/0009-refunds-deferred.md)            | Accepted              | 3     | 2026-05-21 |
| 0010 | [Stock consistency: safety buffer + reconcile cron](adr/0010-stock-consistency.md) | Accepted   | 3.3   | 2026-05-21 |
| 0011 | [Secret в query для Odoo→middleware webhook](adr/0011-secret-in-query-for-odoo-webhook.md) | Accepted | 3.2 | 2026-05-23 |
| 0012 | [Одна ProductType "Generic" для каталога MVP](adr/0012-single-product-type-mvp.md) | Accepted | 3.2 | 2026-05-23 |
| 0013 | [Bulk seed как идемпотентная CLI-команда](adr/0013-bulk-seed-as-cli.md) | Accepted | 3.2 | 2026-05-23 |
| 0014 | [Stock вне scope 3.2 (in scope 3.3)](adr/0014-stock-out-of-scope-3-2.md) | Accepted | 3.2 | 2026-05-23 |
| 0015 | [Single-warehouse MVP (1 Odoo → 1 Saleor)](adr/0015-single-warehouse-mvp.md) | Accepted | 3.3 | 2026-05-23 |
| 0016 | [Safety buffer MAX(qty - buffer, 0)](adr/0016-safety-buffer-policy.md) | Accepted | 3.3 | 2026-05-23 |
| 0017 | [Stock trigger = stock.quant write (quantity)](adr/0017-stock-quant-trigger.md) | Accepted | 3.3 | 2026-05-23 |
| 0018 | [Reconcile cron 02:00 UTC daily, dry-run](adr/0018-reconcile-cron.md) | Accepted | 3.3 | 2026-05-23 |
| 0019 | [Order status mapping Odoo → Saleor](adr/0019-order-status-mapping.md) | Accepted | 3.4 | 2026-05-23 |
| 0020 | [Reverse-echo prevention via skip-guard context](adr/0020-skip-guard-mechanism.md) | Accepted | 3.4 | 2026-05-23 |
| 0021 | [Single full fulfillment per order (MVP)](adr/0021-single-fulfillment-mvp.md) | Accepted | 3.4 | 2026-05-23 |
| 0022 | [Customer notification policy](adr/0022-notification-policy.md) | Accepted | 3.4 | 2026-05-23 |
| 0023 | [Single "Generic" ProductType with variant attributes](adr/0023-product-type-strategy.md) | Accepted | 3.5 | 2026-05-23 |
| 0024 | [Variant SKU = product.product.default_code](adr/0024-variant-sku-natural-key.md) | Accepted | 3.5 | 2026-05-23 |
| 0025 | [Migration policy for single-variant products](adr/0025-variant-migration-policy.md) | Accepted | 3.5 | 2026-05-23 |
| 0026 | [Per-variant per-channel pricing (price_extra)](adr/0026-per-variant-channel-pricing.md) | Accepted | 3.5 | 2026-05-23 |
| 0027 | [Attribute input type DROPDOWN only (MVP)](adr/0027-attribute-dropdown-only-mvp.md) | Accepted | 3.5 | 2026-05-23 |

См. также:
- [Phase 3 research doc](phase-3-integration-research.md) — глубокое исследование, на котором основаны ADRs.
- [ADR README](adr/README.md) — формат и процесс.
