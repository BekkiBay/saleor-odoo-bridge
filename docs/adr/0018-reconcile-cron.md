# ADR-0018: Reconcile cron 02:00 UTC daily, dry-run by default

## Status
Accepted (2026-05-23) — Phase 3.3

## Context

Event-driven sync (ADR-0017) может потерять событие: middleware/worker лежал,
Redis потерял job, Odoo не доставил webhook. Нужен safety net, сверяющий остатки
Odoo vs Saleor и закрывающий дрейф. ADR-0010 предполагал reconcile каждые 5 минут;
на практике для MVP-каталога ежедневной сверки достаточно, а частый bulk-read
нагружает Odoo и Saleor.

## Decision

**Daily reconcile в 02:00 UTC, по умолчанию dry-run (только лог дрейфа).**

1. **arq cron** (`cron_jobs` в `WorkerSettings`): `reconcile_stock_drift` запускается
   ежедневно в 02:00 UTC, всегда в **dry-run** — считает и логирует
   `event=stock_reconcile_drift count=N`, ничего не правит.
2. **Auto-fix только вручную** через CLI с явным флагом:
   ```
   python -m saleor_bridge.cli.bulk_seed reconcile-stocks            # dry-run, exit 1 при дрейфе
   python -m saleor_bridge.cli.bulk_seed reconcile-stocks --apply    # чинит дрейф
   ```
   Оператор смотрит лог/таблицу, решает и применяет осознанно (см. runbook
   `reconcile-procedure.md`).
3. Дрейф = `saleor_qty != MAX(odoo_raw - buffer, 0)` для пары (variant, warehouse).
   Расхождение ровно на `buffer` — это норма (ожидаемый эффект ADR-0016), НЕ дрейф.

`BRIDGE_STOCK_RECONCILE_INTERVAL` (env, дефолт 300) остаётся для возможной смены на
интервальный режим в Phase 4; в 3.3 фактический планировщик — daily arq cron.

## Alternatives considered

- **Auto-apply в cron.** Отброшено: автоматическая правка остатков без
  человека рискованна (баг в агрегации → массовая перезапись). Dry-run + ручной
  `--apply` безопаснее для MVP.
- **Системный cron / Celery beat.** Отброшено: arq уже в стеке, `cron_jobs` —
  ~5 строк, не тянем новый компонент.
- **Каждые 5 минут (как в ADR-0010).** Смягчено до daily: меньше нагрузки,
  event-sync покрывает оперативность; reconcile — это safety net, не основной путь.

## Consequences

**Pros:** автоматический ежедневный детектор дрейфа без риска авто-правки; ручной
apply под контролем; ноль новых компонентов.

**Cons:** до ручного `--apply` или следующего event'а дрейф остаётся (но виден в
логе). При большом каталоге daily bulk-read тяжелеет — tunable в Phase 4.
