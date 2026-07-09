# ADR-0006: Conflict resolution — Odoo всегда побеждает, divergence в chatter

## Status
Accepted (2026-05-21)

## Context

Source-of-truth для каталога / стока / order-статусов = Odoo (см. [research doc §1](../phase-3-integration-research.md)).

Saleor Dashboard всё равно позволяет редактировать product fields (name, description, price). Если оператор изменит товар в Saleor — после следующего push'а из Odoo его изменение затрётся. Это может быть:
- intentional (admin поправил опечатку, потом её перенесли в Odoo);
- unintentional (admin не знал что Saleor read-only);
- legitimate emergency (Odoo down, надо срочно поправить).

Нужна policy.

## Decision

**Odoo always wins** для всех мастер-сущностей: products, variants, categories, attributes, stocks, prices.

При обнаружении divergence (значение в Saleor отличается от Odoo при следующей синке) — middleware **не блокирует sync**, выполняет overwrite, но логирует событие двумя способами:

1. **structlog WARNING** с `event=divergence`, `model=Product`, `saleor_id=...`, `odoo_value=...`, `saleor_value=...`.
2. **Post в chatter** соответствующего `product.template` / `sale.order` — `mail.message` с body: `[Saleor sync] Divergence detected at {timestamp}: field '{name}' was '{saleor_value}' in Saleor, overwritten with '{odoo_value}' from Odoo.`

Operator увидит в Odoo UI на product page вкладку "Messages" с историей divergence. Достаточно для post-mortem без блокировки бизнес-операций.

Для **orders** и **customers** policy инвертирована: Saleor wins (заказ родился на витрине). Дивергенцию здесь регистрируем только если в Odoo появился manual edit `sale.order` после `ORDER_CREATED` (редкий кейс).

## Alternatives considered

1. **Bidirectional sync с conflict markers.** Как git merge conflicts. **Отброшено:** нет UI чтобы оператор разрешал конфликты. Сложно.

2. **Read-only Saleor admin для caталога.** Через Saleor permissions: убрать `MANAGE_PRODUCTS` у staff users. **Отброшено:** заказчик хочет manual override option (emergency-fix). Снимет permission — потеряет fallback.

3. **Stop sync on divergence, alert admin.** **Отброшено:** один divergence блокирует ВСЕ обновления товара. Хрупко.

## Consequences

**Pros:**
- Простая ментальная модель: "Saleor — это окно в Odoo".
- Никаких застоев в sync — overwrite всегда выполняется.
- Audit trail в chatter.

**Cons:**
- Если admin случайно поправил Saleor и не заметил overwrite — изменение потеряно.
- Chatter может засраться сообщениями при частых правках "не в той системе".

**Mitigation:**
- Slack-alert (channel `#saleor-sync-divergence`) на любой divergence event — admin видит сразу.
- Phase 4: dashboard view "divergence in last 24h" с фильтром по моделям.

## Addendum (Phase 3.2 hardening, 2026-05-23)

**Реализованная divergence для product (name):** на update `sync_product` читает
текущее Saleor `name` + `metafields['odoo_synced_name']`; при ручной правке в Saleor
→ chatter `product.template` (`message_post`) + overwrite. Проверено вживую.

**Category parent-move — divergence, которую НЕЛЬЗЯ разрешить overwrite'ом.**
Saleor API не умеет менять parent категории (`CategoryInput` без `parent`, move-мутации
нет — подтверждено интроспекцией). Поэтому при смене `parent_id` в Odoo «Odoo wins»
неприменим. Поведение: `sync_category` детектит расхождение parent (Saleor vs желаемый),
пишет `log.warning('category_parent_diverged')` и помечает `saleor.binding.sync_state=
'diverged'` + `error_message` (видно в Bindings dashboard, фильтр Diverged). Имя при
этом синкается. Полный re-parent — через `wipe`+`bulk-seed` (см. operations.md §4).
У `product.category` нет mail.thread → chatter недоступен, divergence отражаем в binding.

**Layer-уточнение (failed-sync):** Saleor-сторонний сбой синки виден в
`saleor.binding.sync_state='failed'`, а НЕ в `saleor.outbox` (outbox = аудит hop'а
Odoo→middleware, который при сбое Saleor всё равно `confirmed/200`). См.
hardening-results.md §1.
