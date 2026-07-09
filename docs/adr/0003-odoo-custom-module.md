# ADR-0003: Кастомный Odoo-модуль `saleor_sync`

## Status
Accepted (2026-05-21)

## Context

Middleware пушит данные в Odoo через JSON-2 REST API, но нужны Odoo-side артефакты:

1. **External ID mapping** — таблица `(model, odoo_id, saleor_id, last_sync, state)`. Без неё каждое обращение «найди sale.order по Saleor ID» = full table scan по `client_order_ref` (медленно, нет уникальности).

2. **Outbound webhooks** (catalog/stock/order-status в Saleor) — Odoo 19 даёт нативный `ir.actions.server` state='webhook' (см. ADR-0001 research doc §3.3). Серверные действия настраиваются через UI / XML data — это требует Odoo-модуля для версионирования.

3. **Server-side ORM helpers** — методы вроде `sale.order.action_confirm_from_saleor()` (атомарное "confirm + invoice + post + register payment"). Каждый шаг — отдельный JSON-2 call с round-trip и риском transient lock-fail. Один server-side метод = одна транзакция.

4. **Future:** `queue_job` хуки, конвертеры (EditorJS→HTML), миграции (XMLID fixtures).

## Decision

Создаём Odoo Community-модуль **`saleor_sync`** в `odoo/addons/saleor_sync/`. Стандартный layout: `__manifest__`, `models/`, `security/`, `views/`, `data/`.

В **Phase 3.0** модуль содержит только skeleton:
- модель `saleor.binding` (external ID mapping),
- ACL для `saleor.binding`,
- minimal tree/form view,
- пустой `data/ir_actions_server_data.xml` (template для будущих server actions).

В **Phase 3.1+** добавятся: business-logic методы, конкретные `ir.actions.server` records, mapper helpers, EditorJS-converter.

Зависимости в `__manifest__.py`: `sale_management`, `stock`, `account`. **`queue_job` НЕ добавляется в зависимости в Phase 3.0** (его установка требует OCA repo, чтобы не блокировать smoke-test). Добавится в Phase 3.1 когда понадобится — описано в README.

License — LGPL-3 (совместимо с OCA для возможной публикации).

## Alternatives considered

1. **Использовать `ir.model.data` напрямую без своей таблицы.** Стандартный Odoo external-id mechanism. **Отброшено:** XMLID не имеет полей `last_sync_in/out/state/error`. Нужна доменная state-таблица.

2. **Хранить mapping в Redis на стороне middleware.** **Отброшено:** Odoo-side скрипты/cron не имеют доступа к Redis без custom controller. Mapping должна быть видна и Odoo-операторам через Studio/UI.

3. **`OCA/connector` framework.** Backend + Binding + Mapper pattern. **Отброшено для Phase 3.0:** [нет 19.0 порта на май 2026](https://github.com/OCA/connector). Когда выйдет — можно мигрировать.

## Consequences

**Pros:**
- Версионируем server actions и mappings в git (XML data files).
- Operator видит в UI какие записи синкаются (saleor_binding tree view).
- Будущая миграция на OCA/connector — переименование моделей, не переписывание.

**Cons:**
- Required custom-module install для любого окружения (dev/staging/prod).
- Upgrade Odoo (16→17→18→19→20) может требовать adjust модуля (Selection options, API changes).

**Mitigation:** module version pinned в `__manifest__.py` (`'19.0.0.1.0'`). Major-bump Odoo → ревью модуля.
