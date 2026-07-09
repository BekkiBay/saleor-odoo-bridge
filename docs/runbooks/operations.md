# Operations — Odoo ↔ Saleor catalog (Phase 3.2)

Операционные процедуры для каталожной синки. См. также `bulk-seed.md`,
`hardening-results.md`.

Все CLI-команды — внутри middleware-контейнера:
```bash
docker exec marketplace-middleware python -m saleor_bridge.cli.bulk_seed <cmd>
```

## 1. Retry failed sync

Когда binding ушёл в `sync_state='failed'` (Saleor был недоступен и т.п.):

```bash
# 1. посмотреть failed bindings
docker exec marketplace-middleware python -c "
import asyncio,os
from saleor_bridge.odoo.client import OdooClient
async def m():
 o=OdooClient(url=os.environ['BRIDGE_ODOO_URL'],db=os.environ['BRIDGE_ODOO_DB'],api_key=os.environ['BRIDGE_ODOO_API_KEY'])
 print(await o.search_read('saleor.binding',[('sync_state','=','failed')],['model_name','odoo_id','error_message']))
asyncio.run(m())"

# 2. ретрай (outbound: product.template / product.category)
docker exec marketplace-middleware python -m saleor_bridge.cli.bulk_seed retry-failed
```
`retry-failed` берёт все `failed` биндинги, заново гонит sync, печатает
`found/ok/failed/skipped`. Inbound (res.partner/sale.order) пропускаются.

В Odoo также видно в **Saleor Sync → Bindings** (фильтр Failed) и **→ Outbox**.

## 2. Verify binding integrity (cron-able)

```bash
.venv/bin/python scripts/verify_bindings.py   # exit 0 ok, 1 — расхождения
```
Проверяет orphan Odoo / dead binding / orphan Saleor / counts по products и
каталожным категориям. Для cron: ставь на nightly, алерти при exit!=0.

Типовые расхождения и действия:
| Находка | Действие |
|---|---|
| orphan Odoo (товар без binding) | `retry-failed` или `bulk-seed` |
| dead binding (saleor_id нет в Saleor) | `wipe` + `bulk-seed` (полный ресед) |
| orphan Saleor (товар без binding) | удалить в Saleor вручную или `wipe`+`bulk-seed` |
| count mismatch категорий | проверь parent-move divergence (см. §4) |

## 3. Controlled archive / unarchive

Archive товара в Odoo → unpublish в Saleor (не удаляет product):
```bash
# UI: Inventory → Products → выбрать → Action → Archive
# или JSON-2:
docker exec -i odoo-app odoo shell -c /tmp/odoo.conf -d marketplace --no-http <<'PY'
env['product.template'].browse(<ID>).write({'active': False}); env.cr.commit()
PY
```
Через ~5s Saleor: `isPublished=false, isAvailableForPurchase=false`. Unarchive
(`active=True`) → publish обратно. Binding остаётся `synced`.

## 4. Category re-parent (ОГРАНИЧЕНИЕ)

⚠️ **Saleor API не поддерживает смену parent у категории** (`CategoryInput` без
`parent`, move-мутации нет). Rename — синкается; **parent move — нет.**

Что произойдёт при move в Odoo: name обновится, parent в Saleor останется старым,
binding → `sync_state='diverged'` + `error_message`, в логах worker
`category_parent_diverged`. Это видно в **Bindings** (фильтр Diverged).

Как реально перестроить дерево категорий в Saleor:
```bash
docker exec marketplace-middleware python -m saleor_bridge.cli.bulk_seed wipe --yes
docker exec marketplace-middleware python -m saleor_bridge.cli.bulk_seed bulk-seed
```
(`wipe` чистит и Saleor-каталог, и outbound bindings → reseed строит дерево заново.)

## 5. Full reset / reseed

```bash
docker exec marketplace-middleware python -m saleor_bridge.cli.bulk_seed wipe --yes     # DESTRUCTIVE
docker exec marketplace-middleware python -m saleor_bridge.cli.bulk_seed bulk-seed
.venv/bin/python scripts/verify_bindings.py
```
`wipe` удаляет ВСЕ Saleor products+categories и ВСЕ outbound bindings (product.
template/category/type). Без чистки bindings reseed ушёл бы в update по мёртвым id.

## 6. Дедуп и гонки

- Webhook'и дедупятся в arq по `_job_id=odoo:<model>:<id>:<5s-bucket>` (+ `_defer_by=3`).
- Конкурентное создание категории защищено Redis-локом
  `saleor_bridge:lock:product.category:<id>` + partial unique index
  `saleor_binding_model_odoo_uniq (model_name,odoo_id) WHERE odoo_id!=0`.

## 7. Known noise (Phase 4)

При массовых операциях в Odoo (или setup с лежащим middleware) `saleor.outbox`
накапливает `failed`-строки и автоматизация срабатывает многократно на одну запись
(нет `trigger_field_ids`). Не ломает синку (idempotent + dedup). Prune outbox при
необходимости; сужение триггер-полей — Phase 4.
