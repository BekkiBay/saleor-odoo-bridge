# ADR-0013: Bulk seed как идемпотентная CLI-команда, не webhook flow

## Status
Accepted (2026-05-23) — Phase 3.2

## Context

Первичная выгрузка каталога Odoo → Saleor (18 категорий + 30 продуктов) — разовая
операция. Два способа запустить:

1. **Через webhook flow** — заставить Odoo «выстрелить» событиями по всем записям
   (например, массовый `write`). Минусы: зависимость от того, что Odoo сам инициирует
   выгрузку; шумит в outbox/логах; нет управления порядком (категории должны идти
   раньше продуктов); тяжело сделать `--dry-run`.
2. **Через явную CLI-команду** — оператор командует выгрузку, видит план и прогресс.

## Decision

Bulk seed — **отдельная idempotent CLI-команда** (`typer`):

```bash
docker compose exec middleware python -m saleor_bridge.cli.bulk_seed bulk-seed
docker compose exec middleware python -m saleor_bridge.cli.bulk_seed bulk-seed --dry-run
docker compose exec middleware python -m saleor_bridge.cli.bulk_seed wipe   # снести Saleor-каталог
```

- Порядок: ensure ProductType → категории в **топологическом порядке** (родители
  раньше) → продукты батчами.
- **Идемпотентность**: каждый ensure_* сперва ищет `saleor.binding` по `odoo_id`;
  есть → update, нет → create. Повторный прогон не плодит дубли.
- `--dry-run` печатает план (сколько create/update/skip) без мутаций.
- Прогресс — `rich`.
- Не зависит от того, инициирует ли Odoo события: читает каталог из Odoo по JSON-2 и
  пушит сам.

Регулярные изменения (после seed) идут уже через webhook flow
(`base.automation` → `/api/odoo-events` → arq), см. ADR-0011.

## Alternatives considered

- **Webhook-based seed (вариант 1).** Отброшено: нет контроля порядка/плана, шум,
  сложный dry-run.
- **Management-команда внутри Odoo (`odoo shell`).** Отброшено: вся логика маппинга и
  Saleor-клиент живут в middleware (ADR-0001); дублировать в Odoo — плохо.

## Consequences

**Pros:** оператор явно командует, видит план и прогресс; топологический порядок под
контролем; легко повторять (идемпотентно) и тестировать.

**Cons:** ещё одна точка входа (CLI) в middleware-образе → доп. зависимость `typer`.
Приемлемо.
