# ADR-0008: Failed sync — Slack alert + email + admin dashboard, manual intervention

## Status
Accepted (2026-05-21)

## Context

Webhook от Saleor получен, sigverify passed, бизнес-логика sync упала: Odoo вернул 5xx, PG deadlock, ValidationError (SKU не найден), Saleor mutation rate-limited, etc.

Каноничный паттерн (см. [research doc §3.4](../phase-3-integration-research.md)): `queue_job` с `max_retries=5`, exponential backoff. После 5 попыток — job в state `failed`. Что делать дальше?

Варианты:
- **Auto-cancel заказ + refund клиенту.** Хорошо для UX, плохо если проблема transient (Odoo down 10 минут).
- **Email клиенту "проблема с обработкой".** Может напугать.
- **Silence + admin discovers через cron.** Сценарий "узнаём через неделю".

Заказчик согласовал: **alert + manual intervention**.

## Decision

После 5 retry'ев `queue_job` job уходит в state `failed`:

1. **Slack alert** в канал `#saleor-sync-failed` (URL в env `BRIDGE_SLACK_WEBHOOK_URL`, опционально). Payload: event_type, saleor_id, error_message, link на admin dashboard.
2. **Email** на `ops@justix.uz` (адрес в env `BRIDGE_OPS_EMAIL`). То же содержимое.
3. **Admin dashboard** в Odoo: tree view `saleor.binding` с фильтром `sync_state='failed'`, plus stand-alone view `Failed Jobs` (через `queue.job` модель).
4. **No automatic refund / cancel** — оператор решает руками: ретрить, исправить data, cancel order, etc.
5. **Customer not notified** — если sync upstream, клиент уже видит "заказ принят" в Saleor. Решаем за минуты, не часы.

`saleor.binding.sync_state` имеет значение `failed` + `error_message` text-field для diagnostics.

## Alternatives considered

1. **Auto-retry indefinitely.** **Отброшено:** infinite loop на permanent failure (e.g. SKU truly missing). Лучше fail fast, alert.

2. **Auto-cancel order через 24 часа.** **Отброшено:** Заказчик хочет manual control — могут быть legitimate reasons задержки.

3. **Customer-facing notification.** **Отброшено:** noise. Большинство failed sync'ов резолвится за 30 минут.

## Consequences

**Pros:**
- Понятный escalation path.
- Operator контролирует ситуацию (refund / fix / retry).
- Audit trail в `saleor.binding.error_message`.

**Cons:**
- Требует human-on-call (хотя бы в рабочее время).
- Slack + email — double notification noise.
- На раннем этапе много false alerts, пока не отладим edge cases.

**Mitigation:**
- Phase 4: dashboard с **retry button** прямо в Odoo UI. Operator кликнул → job заново.
- Phase 4: rate-limit алертов (дедуп по `(event_type, saleor_id)` за час).
- Slack и Email можно отключать через env (для dev — обычно нет ни Slack ни Email).

**В Phase 3.0 не реализуем сам alert pipeline** — это будет в Phase 3.1 когда появится первый реальный sync. Сейчас фиксируем policy.
