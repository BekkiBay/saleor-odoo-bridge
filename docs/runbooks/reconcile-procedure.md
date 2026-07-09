# Runbook — Stock reconcile procedure (Phase 3.3)

Сверка остатков Odoo vs Saleor и закрытие дрейфа. См. ADR-0018 (и ADR-0016 по
формуле). Дополняет [stock-sync.md](stock-sync.md).

## Что такое дрейф

Для каждой пары (variant, warehouse):

```
expected = MAX(odoo_raw - BRIDGE_STOCK_SAFETY_BUFFER, 0)     # ADR-0016
drift    = saleor_qty != expected
```

Расхождение **ровно на `buffer`** (например Odoo=12, Saleor=11 при buffer=1) — это
**норма**, НЕ дрейф (это и есть эффект safety buffer). Дрейф — когда Saleor
отличается от `expected` (потерянный event, ручная правка в Saleor, баг).

## Когда запускать

- **Автоматически:** arq cron каждый день в **02:00 UTC**, всегда **dry-run** —
  только лог `event=stock_reconcile_drift count=N` (ADR-0018). Ничего не правит.
- **Вручную:** после инцидента (worker/Redis/Odoo лежали), после массовых правок
  остатков, при подозрении на расхождение витрины.

## Dry-run (по умолчанию)

```bash
docker compose exec middleware python -m saleor_bridge.cli.bulk_seed reconcile-stocks
```

Печатает таблицу и сводку. **Exit 0** — чисто, **exit 1** — есть дрейф.

```
        Stock reconcile (dry-run)
 SKU       Warehouse  Odoo  Saleor  Diff   Status
 SKU-001   wh-1       12    11      -1     (buffer — OK)
 SKU-005   wh-1       20    15      -5     ❌ DRIFT
checked=30 ok=29 drift=1 fixed=0
```

- `Odoo` — сырой агрегат (`odoo_raw`).
- `Saleor` — текущий остаток в Saleor (сумма по складам).
- `Diff` = `Saleor - Odoo` (при норме = `-buffer`).
- `Status` — `(buffer — OK)` или `❌ DRIFT`.

## Apply (правка дрейфа)

Сначала посмотри dry-run, убедись что дрейф реальный (а не ожидаемый buffer-зазор).
Затем:

```bash
docker compose exec middleware python -m saleor_bridge.cli.bulk_seed reconcile-stocks --apply
```

Для каждого дрейфного SKU выставляет `trackInventory=True` и пушит `expected`
(`MAX(odoo_raw - buffer, 0)`). **Exit 0** если все правки прошли, **exit 1** при
ошибке хотя бы одной. После `--apply` повтори dry-run — должно быть `drift=0`.

## Проверка работы cron

```bash
# логи worker за ночь:
docker compose logs middleware-worker | grep stock_reconcile_drift
# ручной прогон cron-таски (через arq) для проверки:
docker compose exec middleware python -m saleor_bridge.cli.bulk_seed reconcile-stocks
```

> **Часовой пояс:** cron берёт время контейнера (UTC по умолчанию для python-образа).
> Если контейнеру задан другой TZ — поправь час в `cron(... hour=2 ...)`
> (`queue/arq_worker.py`) или выставь `TZ=UTC`.

## Эскалация

- Дрейф на МНОГИХ SKU сразу → вероятно системная проблема (warehouse↔channel,
  buffer mismatch, потеря всей пачки events). НЕ делай `--apply` вслепую — сначала
  разберись в причине.
- `quantityAvailable=0` при `stocks.quantity>0` → warehouse не в shipping zone
  канала (ADR-0015). `--apply` это не починит — нужна привязка warehouse к каналу.
