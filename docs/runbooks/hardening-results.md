# Phase 3.2 Hardening — результаты верификации

Дата: 2026-05-23. Прогон 5 критичных путей перед Phase 3.3 (stock sync).
Среда: локальный стек (Odoo 19 + middleware + Saleor 3.23), `default-channel`/UZS.

| # | Сценарий | Статус |
|---|----------|--------|
| 1 | Failed-sync alert path | ✅ Pass (1 уточнение) |
| 2 | Fresh install end-to-end | ✅ Pass |
| 3 | Archive flow | ✅ Pass |
| 4 | Category rename + move | ⚠️ rename ✅ / move — ограничение Saleor, обработано |
| 5 | Binding integrity utility | ✅ Pass |

Итог по unit-тестам: **51 passed** (49 базовых + 2 lock).

---

## Сценарий 1 — Failed-sync alert path ✅

**Setup:** локальный HTTP-catcher на `odoo-net` как Slack endpoint
(`BRIDGE_SLACK_WEBHOOK_URL=http://slack-catcher:80/`), `docker stop saleor-api-1`.

**Что увидел (worker logs):**
```
12:29:50 task_failed  evt=ODOO_WRITE saleor_id=1 try_=1  error='All connection attempts failed'
12:29:50 retrying job in 1.00s
12:29:51 task_failed  ... try_=2
12:29:51 retrying job in 4.00s
12:29:55 task_failed  ... try_=3
12:29:55 task_final_failure  evt=ODOO_WRITE saleor_id=1   (+ traceback ConnectError)
```
Backoff `4**(try-1)` → **1s, 4s**, итого 3 попытки (max_tries=3).

**Slack payload (catcher):**
```
{"text":":rotating_light: saleor-bridge sync FAILED\nevent=ODOO_WRITE model=product.template ref=1\nerror=All connection attempts failed"}
```

**Binding:** `saleor.binding(product.template, odoo_id=1).sync_state='failed'`,
`error_message='All connection attempts failed'`.

**Recovery:** `docker start saleor-api-1` → `bulk_seed retry-failed` → `found=1 ok=1`,
binding снова `synced`, error очищен.

**⚠️ Уточнение (не баг):** `saleor.outbox` для этого write = **`confirmed/200`**, НЕ
`failed`. Outbox отражает hop **Odoo → middleware** (middleware принял и поставил job
→ 200). Сбой произошёл позже, на hop **middleware → Saleor**, и он отражён в
`saleor.binding.sync_state='failed'`. Спека ждала `outbox=failed` — это другой слой.
Outbox `failed` ставится только когда сам POST в middleware не прошёл (middleware
лежит / 4xx-5xx).

**Email-путь:** `send_email_alert` вызывается там же, но no-op без `BRIDGE_OPS_EMAIL`/SMTP.

---

## Сценарий 2 — Fresh install end-to-end ✅

**Полный сброс** (`docker compose down -v`) → bases → `odoo_setup.py --reset` →
`generate_api_key.py` → middleware up → `install_bridge_app.py` → wipe → bulk-seed.
Каждая команда exit 0, **без ручных touch'ей между шагами.**

**post_init_hook отработал САМ** (read `ir.config_parameter` через odoorpc, без правок):
```
saleor_sync.middleware_url = http://middleware:8080
saleor_sync.webhook_secret len = 48
server_actions = 2,  automations = 2,  saleor.outbox model = present
```
После: 18 cat + 30 prod в Saleor, 49 outbound bindings, `verify_bindings` clean.

**Наблюдение (concern, не блокер):** при `odoo_setup` (создание 30+18 записей) middleware
был ещё не поднят → каждый Odoo write дёрнул автоматизацию → ~486 `saleor.outbox`
строк `state='failed'` (POST не прошёл, connection refused — мгновенно, без 2s блока).
Это шум, не ломает setup. Также видно, что одна каталожная операция = много write'ов
(Odoo + stock-модуль) → автоматизация без `trigger_field_ids` срабатывает ~10× на
запись. Рекомендация Phase 4: сузить триггер до полей `name/categ_id/list_price/active/
parent_id` (см. operations.md).

---

## Сценарий 3 — Archive flow ✅

`product.template` SKU-005 (Джинсы скинни синие), `write({'active': False})`:
- BEFORE: Saleor `isPublished=true, isAvailableForPurchase=true`.
- AFTER (~5s): `isPublished=false, isAvailableForPurchase=false`.
- binding `synced`, `last_sync_out` обновлён. Ошибок в worker — нет.

**Reverse:** `write({'active': True})` → `isPublished=true, isAvailableForPurchase=true`.

Автоматизация ловит archive потому что у неё **нет** `filter_domain active=True`
(сознательно, см. base_automation_data.xml). Mapper читает `active` и шлёт
`set_product_published(published=product.active)`.

---

## Сценарий 4 — Category rename + move

### 4a Rename ✅
`product.category` "Платья" → "Платья и сарафаны". Через ~5s в Saleor:
`name='Платья и сарафаны'`, parent остался `Одежда`, **3 товара сохранили категорию**
(`products.totalCount=3`).

### 4b Parent move — ⚠️ ограничение Saleor (обработано, не падаем)

**Что сломалось (исходно):** перенос категории под нового родителя в Odoo НЕ менял
parent в Saleor. Плюс гонка плодила дубль категории.

**Корневая причина 1 — re-parent не поддержан Saleor API:**
`CategoryInput` (categoryUpdate) = `[description,name,slug,seo,backgroundImage,
backgroundImageAlt,metadata,privateMetadata]` — **поля `parent` нет**. Parent
выставляется только в `categoryCreate(parent:)`. Move-мутации в Saleor 3.23 нет.

**Решение (ADR-0006, decision «document + warn»):** при апдейте категории
`sync_category` сверяет текущий Saleor-parent с желаемым; при расхождении —
`log.warning('category_parent_diverged')` + `saleor.binding.sync_state='diverged'` +
`error_message`. Имя всё равно обновляется. Re-parent делается через `wipe`+`bulk-seed`.

Проверка после фикса:
```
worker: category_parent_diverged desired_parent=...109 odoo_id=19 saleor_parent=...103
binding cat 19: sync_state='diverged'  error='parent-move not propagated: Odoo parent=24 ... != Saleor parent ...'
```

**Корневая причина 2 — дубль категории (гонка):** категорию 22 создавал её
собственный webhook-job И рекурсивный ensure-parent из job'а ребёнка (19) → оба не
видели binding → оба создавали. `saleor.binding` не имел `UNIQUE(model_name, odoo_id)`.

**Фикс:** (a) Redis-лок `saleor_bridge:lock:product.category:<id>` вокруг
check-or-create в `sync_category` (`middleware/src/saleor_bridge/locks.py`);
(b) partial unique index `saleor_binding_model_odoo_uniq (model_name, odoo_id) WHERE
odoo_id != 0` как backstop.

Проверка после фикса (тот же burst create+move):
```
Женское в Saleor: 1 (дубля нет)   |   binding для Женское: 1   |   total Saleor cats: 19
```

---

## Сценарий 5 — Binding integrity utility ✅

Создан `scripts/verify_bindings.py`. Проверяет orphan Odoo / dead binding / orphan
Saleor / counts, по products и каталожным категориям (достижимым от активных товаров,
Odoo-дефолты исключены). Exit 0/1.

- На чистом состоянии: **All checks passed** (30/30/30, 18/18/18).
- Корректно поймал дрейф 4b: `count mismatch (product.category): odoo=19 saleor=21
  bindings=21`, exit 1. После фиксов и cleanup — снова clean.

---

## Что починено в этой фазе

| Находка | Фикс | Файл |
|---|---|---|
| 4b parent-move молча терялся | detect + warn + binding `diverged` | `usecases/sync_category_to_saleor.py`, `adapters/saleor/category_mutations.py` |
| 4b дубль категории (гонка) | Redis-лок per (model,odoo_id) | `locks.py`, usecases + tasks/bulk_seed прокидывают `redis_url` |
| дубль bindings возможен | partial unique index | `odoo/.../models/saleor_binding.py` (`init()`) |
| `wipe` оставлял мёртвые bindings → reseed падал на update | `wipe` чистит outbound bindings | `adapters/odoo/binding.py` `delete_outbound()`, CLI `wipe` |
| не было retry для failed | CLI `retry-failed` | `cli/bulk_seed.py`, `usecases/bulk_seed.py` `run_retry_failed()` |
| не было проверки целостности | `verify_bindings.py` | `scripts/verify_bindings.py` |

## Открытые вопросы / Phase 4

- `base.automation` без `trigger_field_ids` → ~10× лишних dispatch на 1 каталожную
  операцию. Сузить триггер-поля.
- Category re-parent: при необходимости полноценного move — реализовать
  delete+recreate субдерева с переносом товаров (сейчас: divergence-флаг + wipe/seed).
- `saleor.outbox` не отражает Saleor-сторонний сбой (только Odoo→middleware hop).
  Опционально: middleware-callback в outbox на финальном фейле.

## Готовность к Phase 3.3

✅ **Ready.** Все 5 путей проверены, найденное починено, целостность зелёная,
51 unit-тест, fresh install воспроизводим без ручных шагов.
