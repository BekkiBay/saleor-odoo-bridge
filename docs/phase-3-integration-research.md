# Phase 3 Discovery — Saleor ↔ Odoo Integration Research

**Status:** Spike / research, no code.
**Audience:** Заказчик (принимает архитектурные решения), Claude Code (исполнитель Phase 3.x).
**Date:** 2026-05-21.
**Saleor target:** 3.23.5 (self-hosted в `jutsix-market/saleor/`, не Cloud — важно).
**Odoo target:** 19 Community (локально через `odoo-saleor-integration/`).
**Channel:** один — `default-channel` (UZS).

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Saleor side — API и события](#2-saleor-side--api-и-события)
3. [Odoo side — API и события](#3-odoo-side--api-и-события)
4. [Mapping — Saleor ↔ Odoo](#4-mapping--saleor--odoo)
5. [Архитектурные опции](#5-архитектурные-опции)
6. [Existing landscape — что уже сделано](#6-existing-landscape--что-уже-сделано)
7. [Open questions для заказчика](#7-open-questions-для-заказчика)
8. [Risks и mitigations](#8-risks-и-mitigations)
9. [MVP scope — поэтапная раскатка](#9-mvp-scope--поэтапная-раскатка)
10. [Recommended next step](#10-recommended-next-step)

---

## 1. Executive Summary

### Что рекомендую

**Option A: Lightweight middleware + Odoo custom module.** Конкретно:

1. **Saleor App** — отдельный TypeScript / Next.js сервис на базе [`@saleor/app-sdk` 1.0](https://docs.saleor.io/developer/extending/apps/developing-apps/app-sdk/overview) ([1.0 вышел в марте 2025](https://saleor.io/blog/2025-march-update)). Принимает Saleor webhooks (`ORDER_CREATED`, `ORDER_PAID`, `CUSTOMER_*`), верифицирует подпись через JWS, кладёт работу в очередь и форвардит в Odoo через новый **`/json/2/` REST API Odoo 19**.
2. **Odoo custom module `saleor_sync`** — даёт:
   - external-ID mapping таблицу (`ir.model.data` + `saleor.binding`),
   - outbound webhooks через **нативный `ir.actions.server` со `state='webhook'`** (это в core Community, я перепроверил),
   - конвертеры (EditorJS ↔ HTML, address split, currency).
3. **Очередь** — [`OCA/queue_job` 19.0.2.0.1](https://github.com/OCA/queue/tree/19.0/queue_job) на стороне Odoo для retry/idempotency. На стороне Saleor App — Redis или встроенная очередь в Next.js (`@saleor/app-sdk` поддерживает APL — App Persistence Layer).
4. **Источник истины распределён по сущностям** (Mirumee Lifesize pattern):
   - Каталог, цены, остатки: **Odoo → Saleor** (push).
   - Заказы, новые клиенты: **Saleor → Odoo** (push).
   - Статусы заказа после оплаты/фулфилмента: **Odoo → Saleor** (push).

### Почему именно так

- **Это первая в мире Saleor↔Odoo интеграция** — публичных production-проектов нет ни на GitHub, ни в Saleor App Store, ни в OCA. Решение строится с нуля; чем меньше слоёв, тем меньше технического долга. Это закрывает Option C (Airbyte/n8n) — там нет ни Saleor-коннектора, ни pattern'а для двусторонней синки.
- **Odoo 19 убрал главное препятствие** — нативный `webhook` server action в core (`addons/base/models/ir_actions.py`) и новый `/json/2/` REST API делают custom-middleware намного тоньше, чем это было в 17/18.
- **Saleor 3.21+ subscription queries в webhooks** позволяют payload'у приходить уже отфильтрованным (никаких лишних GraphQL round-trip'ов на receiver'е).
- **Saleor App pattern из `github.com/saleor/apps`** — TypeScript + Next.js + Vercel — это канон, по которому идут все официальные приложения (avatax, stripe, klaviyo и т.д.). Это известный паттерн для будущих разработчиков и hire'ов.

### Главные риски (детально в §8)

1. **Eventual consistency на стоке.** Last-item race: на витрине в Saleor показан остаток 1, два клиента кладут в корзину одновременно, оба оплачивают, в Odoo приходит -2. **Mitigation:** stock reservation на стороне Saleor + рекомендация держать буфер (показывать `MAX(qty-1, 0)` или использовать Saleor `quantityAllocated`). Полностью убрать невозможно без переноса source-of-truth по стоку в Saleor.
2. **Отсутствие официального Saleor Python SDK.** TypeScript-only — значит middleware на TS, контекст разработки расщепляется (Python в Odoo + TS в Saleor App). **Mitigation:** принять как данность; либо использовать [community `mirumee/saleor-app-framework-python`](https://mirumee.github.io/saleor-app-framework-python/) (но он "still in development").
3. **Saleor webhook timeout 20 секунд (≤2 сек реалистично).** Если Odoo медленный или JSON-2 запросы стекаются — Saleor решит, что доставка не удалась, и начнёт retry. **Mitigation:** webhook handler принимает payload, кладёт в очередь, возвращает 200 — реальная работа уходит в queue_job на Odoo.

### Оценка трудозатрат

| Фаза | Что | Часы Claude Code | Часы ручной работы заказчика |
|---|---|---|---|
| 3.0 Подготовка | Регистрация Saleor App, токены, ngrok, custom module skeleton | 4 | 2 (создать API key, ngrok-домен) |
| 3.1 Saleor → Odoo (orders + customers) | Webhook handlers `ORDER_CREATED`/`ORDER_PAID`/`CUSTOMER_*`, mapper, queue_job | 12 | 1 (тест-заказ через storefront) |
| 3.2 Odoo → Saleor (каталог) | `product.template/product.product` → Saleor `productCreate`/`productUpdate`, без variants | 16 | 2 (валидация в Dashboard) |
| 3.3 Stock sync Odoo → Saleor | `stock.quant` change → `productVariantStocksUpdate` | 8 | 1 |
| 3.4 Order status Odoo → Saleor | После confirm/cancel/fulfilment → `orderUpdate`/`orderFulfill` | 8 | 1 |
| 3.5 Variants + attributes | Полноценные variants (size/color), Odoo PTAV ↔ Saleor attributes | 16 | 2 |
| 3.6 Refunds + cancellations | Полные/частичные возвраты, `account.payment` proper flow | 12 | 2 |
| **Итого до production-ready** | | **≈76 ч** (≈2 недели) | **≈11 ч** |

Это **только Claude Code time** — без production deploy, мониторинга, нагрузочного тестирования. Production-ready полный (Phase 4): +30-40 часов.

---

## 2. Saleor side — API и события

### 2.1 Saleor App framework

**Что это.** Saleor App — отдельный HTTP-сервис, который integrator хостит сам. Saleor Core хранит только URL манифеста, токен и подписки на webhooks. Источник: [Apps Overview](https://docs.saleor.io/developer/extending/apps/overview), [Installing and Managing Apps](https://docs.saleor.io/developer/extending/apps/installing-apps).

**Установка** — три пути:
1. CLI (только dev).
2. GraphQL `appInstall` мутация (используется Marketplace).
3. Saleor Dashboard → Apps → Install (UI обёртка над мутацией).

Пример мутации (verbatim из доки):

```graphql
mutation {
  appInstall(
    input: {
      appName: "Justix Odoo Sync"
      manifestUrl: "https://saleor-sync.justix.uz/api/manifest"
      permissions: [MANAGE_ORDERS, MANAGE_PRODUCTS, MANAGE_USERS]
    }
  ) {
    appInstallation { id status appName manifestUrl }
    appErrors { field message code permissions }
  }
}
```

**Token exchange.** Если в манифесте задан `tokenTargetUrl`, Saleor POST'ит туда с `auth_token` в body. App сохраняет токен и должен вернуть HTTP 200. Flow должен быть **идемпотентным** — Saleor может ретраить.

**Auth model:**
- **App token** — long-lived, opaque bearer, шлётся как `Authorization: Bearer <token>`. Используется для server-side вызовов GraphQL ([Authentication](https://docs.saleor.io/api-usage/authentication)).
- **User JWT** — short-lived, для дашборд-iframe (нам не нужно).

**Permissions для нашего use-case** (из [PermissionEnum](https://docs.saleor.io/api-reference/users/enums/permission-enum)):

| Permission | Зачем |
|---|---|
| `MANAGE_ORDERS` | Читать/писать orders, fulfilments |
| `MANAGE_ORDERS_IMPORT` | Требуется для `orderBulkCreate` (миграции, если будут) |
| `MANAGE_PRODUCTS` | CRUD на products, variants, stocks |
| `MANAGE_PRODUCT_TYPES_AND_ATTRIBUTES` | Создавать/менять схему атрибутов |
| `MANAGE_USERS` | CRUD клиентов |
| `MANAGE_CHANNELS` | Если решим multi-channel |
| `MANAGE_SHIPPING` | Warehouses ↔ shipping zones |

**Манифест** — обязательные поля: `id`, `version`, `name`, `permissions`. Полная схема: [App Manifest](https://docs.saleor.io/developer/extending/apps/architecture/manifest).

**SDK.** `@saleor/app-sdk` (TypeScript) — официальный, [1.0 вышел в марте 2025](https://saleor.io/blog/2025-march-update). Покрывает APL, webhook signature verification, Next.js/Lambda/Cloudflare Workers handlers. Python: **официального SDK нет**, есть [community `mirumee/saleor-app-framework-python`](https://mirumee.github.io/saleor-app-framework-python/) с пометкой "still in development". → Рекомендация: TS.

### 2.2 Webhooks — что доступно

#### Async events (главное для нас)

Полный enum: [`WebhookEventTypeAsyncEnum`](https://docs.saleor.io/api-reference/webhooks/enums/webhook-event-type-async-enum). Релевантные для нашего use-case:

**Orders:** `ORDER_CREATED`, `ORDER_CONFIRMED`, `ORDER_PAID`, `ORDER_FULLY_PAID`, `ORDER_REFUNDED`, `ORDER_FULLY_REFUNDED`, `ORDER_UPDATED`, `ORDER_CANCELLED`, `ORDER_EXPIRED`, `ORDER_FULFILLED`, `ORDER_METADATA_UPDATED`, `ORDER_BULK_CREATED`.

**Customers:** `CUSTOMER_CREATED`, `CUSTOMER_UPDATED`, `CUSTOMER_DELETED`, `CUSTOMER_METADATA_UPDATED`.

**Products:** `PRODUCT_CREATED`, `PRODUCT_UPDATED`, `PRODUCT_DELETED`, `PRODUCT_METADATA_UPDATED`.

**Variants:** `PRODUCT_VARIANT_CREATED/UPDATED/DELETED`, `PRODUCT_VARIANT_OUT_OF_STOCK`, `PRODUCT_VARIANT_BACK_IN_STOCK`, `PRODUCT_VARIANT_STOCK_UPDATED`.

**Checkouts (опционально):** `CHECKOUT_CREATED`, `CHECKOUT_FULLY_PAID`.

**Fulfillments:** `FULFILLMENT_CREATED`, `FULFILLMENT_APPROVED`, `FULFILLMENT_CANCELED`, `FULFILLMENT_TRACKING_NUMBER_UPDATED`.

#### Sync events

Полный enum: [`WebhookEventTypeSyncEnum`](https://docs.saleor.io/api-reference/webhooks/enums/webhook-event-type-sync-enum). Нам **не нужны** для phase 3 — это для интеграций налогов, шипинга, payment gateway. У нас уже есть `payments` сервис.

#### Timeout и retry policy ([Webhooks Overview](https://docs.saleor.io/developer/extending/webhooks/overview), [Asynchronous Events](https://docs.saleor.io/developer/extending/webhooks/asynchronous-events))

| Параметр | Значение |
|---|---|
| Network connection timeout | **2 секунды** |
| Total response timeout | **20 секунд** |
| Retry count (async) | **5 попыток** |
| Backoff | exponential: `10 * 2^retries` → 10s, 20s, 40s, 80s, 160s |
| Retry triggers | connection failure, timeout, **5xx**. **НЕ ретраит** на 3xx, 4xx. |

**Дизайн-вывод:** webhook handler должен возвращать 200 как можно быстрее (ack receipt → enqueue → real work async). Реальная работа в Odoo занимает 100ms–10s, плюс может упереться в lock — нельзя делать её inline. См. Architecture Option A.

#### Subscription queries

Saleor 3.x позволяет в webhook прописать GraphQL subscription string — payload приходит уже отфильтрованным ([Subscription Webhook Payloads](https://docs.saleor.io/developer/extending/webhooks/subscription-webhook-payloads)).

```graphql
subscription {
  event {
    ... on OrderCreated {
      order {
        id number created channel { slug currencyCode }
        user { id email firstName lastName }
        billingAddress { firstName lastName streetAddress1 city postalCode country { code } phone }
        shippingAddress { firstName lastName streetAddress1 city postalCode country { code } phone }
        lines {
          id productName variantName productSku quantity
          unitPrice { gross { amount currency } net { amount currency } }
          totalPrice { gross { amount } net { amount } }
          variant { id sku }
        }
        total { gross { amount currency } net { amount } tax { amount } }
        shippingPrice { gross { amount } }
        paymentStatus status
      }
    }
  }
}
```

Channel-фильтрация (Saleor 3.20+):

```graphql
subscription {
  orderCreated(channels: ["default-channel"]) { order { id } }
}
```

#### Подпись (signature)

Saleor 3.5+ использует **JWS с RS256** ([Payload Signature](https://docs.saleor.io/developer/extending/webhooks/payload-signature)). Public key — на `https://<saleor-domain>/.well-known/jwks.json`. Header — `Saleor-Signature`.

Legacy mode: **HMAC-SHA256** через `secretKey` на webhook'е, header `Saleor-HMAC-SHA256`. **У тебя уже используется HMAC** в `storefront/app/api/webhooks/saleor/categories/route.ts` — но это deprecated path; Saleor 4.0 уберёт его. Рекомендация: новые webhooks делать через JWS.

В TypeScript достаточно вызвать `withWebhookSignatureVerified` из `@saleor/app-sdk` — он сам сходит за JWKS и проверит. В Python — fetch JWKS, verify detached JWS вручную (есть библиотеки `python-jose`, `joserfc`).

#### Delivery guarantees

**At-least-once.** Saleor явно не пишет, но 5 retry'ев означают, что дубликаты возможны. **Дедупликации со стороны Saleor нет** — `Saleor-Event-Delivery-Id` header **не документирован** (искал [discussion #9822](https://github.com/saleor/saleor/discussions/9822)).

→ **Идемпотентность — на нашей стороне.** Доменный ключ: `(event_type, order_id, payload_hash)` или `(event_type, order_id, updatedAt)`. Хранить в Redis с TTL 24 часа.

### 2.3 GraphQL API

**Endpoint:** `<saleor-domain>/graphql/`. У нас локально — `http://localhost:8000/graphql/`.

**Auth:** `Authorization: Bearer <app-token>`, `Content-Type: application/json`.

**Rate limits и query complexity** ([Usage Limits](https://docs.saleor.io/api-usage/usage-limits)):

| Сценарий | Лимит |
|---|---|
| Saleor Cloud Sandbox | 120 req/min |
| Saleor Cloud Production | **не документировано** |
| Self-hosted (наш случай) | **нет лимита** |
| Query cost ceiling | **50 000** на запрос |
| Pagination `first`/`last` | макс **100** на страницу |

**Bulk mutations:**
- `orderBulkCreate`: **50 заказов на вызов**, требует `MANAGE_ORDERS_IMPORT` ([orderBulkCreate](https://docs.saleor.io/api-reference/orders/mutations/order-bulk-create)).
- `productBulkCreate`, `productVariantBulkCreate`: **hard limit не документирован**, гайд из [Bulk Operations](https://docs.saleor.io/developer/bulks/overview) — "не более 100 объектов на запрос" как best practice.

### 2.4 Каталог и склад

**Модель:**
- `Product` — родительский SKU concept, привязан к `ProductType`.
- `ProductType` — определяет какие атрибуты применяются и есть ли variants.
- `ProductVariant` — цены и стоки **per variant**, не per product.
- `Attribute` + `AttributeValue` — глобальный pool атрибутов.
- `Category` — дерево (single parent).
- `Collection` — many-to-many группировка (для маркетинга).

**Multi-channel:**
- `ProductChannelListing` — публикация per channel (`isPublished`, `availableForPurchase`, `visibleInListings`).
- `ProductVariantChannelListing` — **деньги** per (variant × channel): `price`, `costPrice`, `priorPrice`.

→ Если у нас один channel — `ProductChannelListing` тривиален. Если multi-channel (RU + UZ) — каждый product → N `ProductChannelListing` + каждый variant → N `ProductVariantChannelListing`. См. [open question §7](#7-open-questions-для-заказчика) про multi-channel.

**Stock model.** `Stock` — связь (variant × warehouse) с полями `quantity`, `quantityAllocated`, `quantityReserved` ([Stock Overview](https://docs.saleor.io/developer/stock/overview)).

Mutations: `productVariantStocksCreate`/`Update`/`Delete`. Per-variant tracking гейтится `productVariant.trackInventory`.

### 2.5 Версия Saleor у пользователя

Узнаём через GraphQL:

```graphql
query { shop { version schemaVersion } }
```

`version` требует `AUTHENTICATED_STAFF_USER` или `AUTHENTICATED_APP`; `schemaVersion` (вид `"3.23"`) — public.

**Релизные ветки на май 2026** (источник — releases страница `saleor/saleor`):

| Версия | Дата | Статус |
|---|---|---|
| 3.23.5 | 2026-05-11 | Latest stable |
| 3.22.50 | 2026-05-05 | LTS-style 3.22 |
| 3.21.58 | 2026-05-05 | LTS-style 3.21 |
| 3.20.116 | — | End-of-line |

У нас в репо — Saleor 3.23 (`ghcr.io/saleor/saleor:3.23`, см. `saleor/docker-compose.yml`). Совместимо.

---

## 3. Odoo side — API и события

### 3.1 Новый JSON-2 REST API (Odoo 19)

**Главное открытие ресёрча:** Odoo 19 ввёл **новый REST API** `/json/2/<model>/<method>` — это рекомендованный способ интеграции. XML-RPC и JSON-RPC явно помечены "scheduled for removal in Odoo 22 (fall 2028)" в [External JSON-2 API doc](https://www.odoo.com/documentation/19.0/developer/reference/external_api.html).

**Endpoint shape:**

```
POST /json/2/<model>/<method>
Authorization: bearer <api-key>
X-Odoo-Database: <db-name>   # только если хост обслуживает несколько БД
Content-Type: application/json
```

**Body:** JSON-объект с `ids`, `context`, и **named kwargs** (positional args не поддерживаются).

**API ключи** создаются через *Preferences → Account Security → New API Key*. **Максимальный TTL: 3 месяца**, после — ротация. Значение показывается один раз. → Нужен будет процесс ротации ключа.

**Пример вызова** (verbatim из доки):

```python
import requests

BASE = "http://localhost:8069/json/2"
HEADERS = {
    "Authorization": f"bearer {API_KEY}",
    "X-Odoo-Database": "marketplace",
}

# search_read
r = requests.post(
    f"{BASE}/res.partner/search_read",
    headers=HEADERS,
    json={
        "context": {"lang": "ru_RU"},
        "domain": [("is_company", "=", False)],
        "fields": ["name", "email"],
        "limit": 100,
    },
)
partners = r.json()

# create
r = requests.post(
    f"{BASE}/sale.order/create",
    headers=HEADERS,
    json={"vals_list": [{"partner_id": 7, "client_order_ref": "saleor-checkout-xyz"}]},
)
new_ids = r.json()

# action_confirm
r = requests.post(
    f"{BASE}/sale.order/action_confirm",
    headers=HEADERS,
    json={"ids": new_ids},
)
```

**Транзакции:** каждый HTTP-запрос — отдельная PG-транзакция. Нельзя chain несколько вызовов в одной транзакции. → Композиционные операции должны идти через server-side методы (`sale.order._create_invoices()` уже атомарен).

**Важная оговорка из доки:** *"Access to data via the external API is only available on Custom Odoo pricing plans"* — это политика **odoo.com SaaS-хостинга**. Для self-hosted Community endpoint открыт (контроллер в open-source `odoo/http.py`). У нас self-hosted, ограничения нет.

### 3.2 Legacy XML-RPC / JSON-RPC (что мы уже используем)

В `scripts/lib/client.py` у нас `odoorpc.ODOO` — это JSON-RPC клиент. Работает на Odoo 19, но deprecation в Odoo 22 — повод **в новом коде использовать JSON-2** напрямую через `requests`.

Текущий код знает:
- `odoo.env[model].search/read/create/write/browse`
- `odoo.db.list/create/drop`
- логин через `odoo.login(db, user, pass)`

Минусы legacy:
- Сессионная авторизация (cookie/uid) вместо bearer-токена.
- Тяжелее scale'ить (sessions ↔ workers).
- Магия (proxy объекты, `.with_context()` — отлично для прототипа, но скрывает что реально летит на wire).

→ **Для Phase 3 пишем новый middleware на JSON-2 + `requests.Session`**. Старый `odoorpc` оставляем только для CLI-скриптов в `scripts/` (orchestrator, setup).

### 3.3 Outbound webhooks из Odoo Community (главное открытие №2)

**Это работает в Community без Studio.** Я перепроверил в исходниках 19.0.

В `odoo/addons/base/models/ir_actions.py` есть `state='webhook'` для `ir.actions.server`:

```python
state = fields.Selection([
    ('object_write', 'Update Record'),
    ('object_create', 'Create Record'),
    ('object_copy', 'Duplicate Record'),
    ('code', 'Execute Code'),
    ('webhook', 'Send Webhook Notification'),   # <-- core!
    ('multi', 'Multi Actions')], ...)

webhook_url = fields.Char(string='Webhook URL', ...)
webhook_field_ids = fields.Many2many(
    'ir.model.fields', ...,
    help="Fields to send in the POST request. "
         "The id and model of the record are always sent as '_id' and '_model'. "
         "The name of the action that triggered the webhook is always sent as '_name'.")
```

Runner (excerpt):

```python
def _run_action_webhook(self, eval_context=None):
    record = self.env[self.model_id.model].browse(self.env.context.get('active_id'))
    vals = {'_model': self.model_id.model, '_id': record.id,
            '_action': f'{self.name}(#{self.id})'}
    if self.webhook_field_ids:
        vals.update(record.read(self.webhook_field_ids.mapped('name'), load=None)[0])
    json_values = json.dumps(vals, sort_keys=True, default=str)

    @self.env.cr.postcommit.add
    def _add_post_commit():
        import requests
        try:
            response = requests.post(url, data=json_values,
                                     headers={'Content-Type': 'application/json'},
                                     timeout=1)
            response.raise_for_status()
        except requests.exceptions.ReadTimeout:
            _logger.warning("Webhook call timed out after 1s ...")
        except requests.exceptions.RequestException as e:
            _logger.warning("Webhook call failed: %s", e)
```

**Гочи которые надо знать:**
- **Timeout 1 секунда захардкожен.** Если наш middleware не отвечает за 1 секунду — Odoo log warning и забывает. Если middleware упал — webhook потерян. Native retry нет.
- **Постcommit semantics:** если SQL транзакция роллбекнётся — webhook не уйдёт (это хорошо для консистентности).
- **Payload — простой JSON** со схемой `{_model, _id, _action, <selected fields>}`. **HMAC подписи нет.** → Custom headers/signature через wrapping `code` server action или через custom модуль.

#### `base_automation` — триггер на ORM event'ы

Модуль [`base_automation`](https://github.com/odoo/odoo/blob/19.0/addons/base_automation/__manifest__.py) — LGPL-3, core, Community-installable. Trigger типы (из [`models/base_automation.py`](https://github.com/odoo/odoo/blob/19.0/addons/base_automation/models/base_automation.py)):

- `on_create`, `on_create_or_write`, `on_priority_set`
- `on_write`, `on_archive`, `on_unarchive`, `on_unlink`
- `on_time`, `on_time_created`, `on_time_updated` (cron-driven)
- `on_message_received`, `on_message_sent`
- `on_user_set`, `on_tag_set`, `on_stage_set`, `on_state_set`
- **`on_webhook`** (inbound — Odoo принимает POST)

**Рецепт "когда `sale.order.state` стал `sale` — пинг в Saleor":**

1. `ir.actions.server` с `state='webhook'`, `model_id='sale.order'`, `webhook_url='https://middleware/odoo/order-confirmed'`, `webhook_field_ids=[id, name, state, partner_id, amount_total, client_order_ref]`.
2. `base.automation` с `trigger='on_state_set'`, `trigger_field_ids=[state]`, `action_server_ids=[<id выше>]`.

#### Inbound webhooks (Saleor → Odoo)

Тот же `base_automation` с `trigger='on_webhook'` даёт URL `/web/hook/<uuid>` (`webhook_uuid = fields.Char(default=lambda self: str(uuid4()))`). Доступен в Community — Studio нужен только для UI-обёртки.

В нашей архитектуре **inbound webhooks Odoo НЕ нужны** — middleware пушит данные через `/json/2/` API напрямую, минуя webhook-слой.

#### OCA webhook модули

`gh search repos "OCA webhook"` — выделенного OCA/webhook нет. Сторонний [Webhook Event Engine](https://apps.odoo.com/apps/modules/19.0/odoo_webhook_engine) на Apps Store — paid/license неясен, **не рекомендую**.

### 3.4 `queue_job` — must-have для resilience

[`OCA/queue/queue_job @ 19.0.2.0.1`](https://github.com/OCA/queue/tree/19.0/queue_job) — Mature, LGPL-3, maintainers `guewen, sbidoul`. Даёт persistent job queue на базе `queue.job` model + jobrunner процесс с PG `NOTIFY` для low-latency dispatch.

**Идиоматичное использование:**

```python
class SaleorBackend(models.Model):
    _inherit = 'saleor.backend'

    def button_sync_products(self):
        self.with_delay(priority=10, eta=60, max_retries=5).import_products_batch()

    def import_products_batch(self):
        for sku in self._fetch_saleor_skus():
            self.with_delay(priority=20, identity_key=f'sku-{sku}').import_one(sku)

    def import_one(self, sku):
        ...  # actual sync; queue_job auto-retries on RetryableJobError
```

`with_delay` props: `priority`, `eta` (delay), `max_retries`, `description`, `channel`, **`identity_key`** (дедупликация — несколько Saleor webhooks для одного product не дублируют джобу).

**Channels** позволяют кэпать concurrency per тип работы: `root.heavy:1` для bulk-import, `root.light:4` для stock updates.

Testing helper:

```python
from odoo.addons.queue_job.tests.common import trap_jobs

def test_my_sync(self):
    with trap_jobs() as trap:
        self.env['saleor.backend'].button_sync_products()
        trap.assert_jobs_count(1, only=self.env['saleor.backend'].import_products_batch)
```

`QUEUE_JOB__NO_DELAY=1` env var обходит очередь — выполняет sync (полезно для dev).

### 3.5 Ключевые модели для маппинга

Краткая шпаргалка (полный mapping — §4):

| Модель | Файл (19.0) | Ключевые поля |
|---|---|---|
| `res.partner` | `odoo/addons/base/models/res_partner.py` | `name`, `email`, `phone`, `parent_id`, `type` ∈ contact/invoice/delivery/other, `street`, `city`, `country_id`, `vat`, `lang`, `is_company`, `customer_rank` |
| `product.template` | `addons/product/models/product_template.py` | `name`, `default_code`, `categ_id`, `list_price`, `standard_price`, `is_storable`, `barcode`, `description_sale`, `attribute_line_ids` |
| `product.product` | `addons/product/models/product_product.py` | `default_code`, `barcode`, `product_tmpl_id`, `product_template_attribute_value_ids`, `qty_available`, `virtual_available` |
| `product.attribute` + `.value` + `.template.attribute.line` + `.template.attribute.value` | те же | См. §4.3 — 4-уровневая модель |
| `product.category` | `addons/product/models/product_category.py` | `name`, `parent_id`, `complete_name`, `parent_path` |
| `sale.order` | `addons/sale/models/sale_order.py` | `name`, `partner_id`, `partner_invoice_id`, `partner_shipping_id`, `order_line`, `state` ∈ draft/sent/sale/cancel, `client_order_ref`, `amount_total`, `currency_id`. **`done` state удалён в 19**, теперь `state='sale' AND locked=True` |
| `sale.order.line` | те же | `product_id`, `product_uom_qty`, `price_unit`, `tax_id`, `discount` |
| `account.move` (invoice) | `addons/account/models/account_move.py` | `move_type='out_invoice'`, `invoice_origin`, `payment_state`, `invoice_line_ids` |
| `stock.warehouse` | `addons/stock/models/stock_warehouse.py` | `name`, `code` (≤5 chars!), `partner_id`, `lot_stock_id` |
| `stock.quant` | `addons/stock/models/stock_quant.py` | `product_id`, `location_id`, `quantity` (**readonly!**), `reserved_quantity` |
| `stock.move` / `stock.picking` | те же | Для изменения остатков надо писать сюда, не в quant напрямую |

**Многоязычность.** Translatable fields декларируются `translate=True`. Storage в 16+ — JSONB колонка на той же строке, ключ — lang code. Чтение/запись через context:

```python
Tmpl.with_context(lang='ru_RU').write({'name': '...'})
Tmpl.with_context(lang='uz_UZ').write({'name': '...'})
```

Lang codes — `res.lang.code` (`ru_RU`, `uz_UZ`, `en_US`).

### 3.6 Ограничения и подводные камни

**SQL/Python constraints.** Через JSON-2 violation возвращается HTTP 4xx/5xx с JSON `{name: 'odoo.exceptions.ValidationError', message, arguments, ...}`. **Транзакция роллбэкается целиком** — для bulk import надо ретраить весь batch.

**Computed/stored fields.** Главный killer для bulk import — каждый `create()` пересчитывает stored computed. Mitigation:
- `precompute=True` на computed (Odoo 17+) — считается один раз в create без depends-trigger.
- `vals_list` в `create` — batched.
- `with_context(tracking_disable=True, mail_create_nolog=True, mail_notrack=True)` — выключает chatter overhead.
- `no_automation=True` — пропускает `base_automation` rules (использовать осторожно — иначе наши собственные outbound webhooks не сработают).

**Concurrent locks.** PG row-level lock в `READ COMMITTED` isolation. Два worker'а пишут одну `sale.order` — второй блокируется на `SELECT FOR UPDATE`, потом проходит. На inventory ops Odoo retry'ит `SerializationFailure` 5 раз (`odoo.service.model.retrying`). → Идемпотентность через `client_order_ref = saleor-order-<id>` обязательна.

**Access rights.** Создать **отдельного bot user** для middleware. Группа `base.group_user` + минимальные app-группы (`sales_team.group_sale_salesman_all_leads`, `stock.group_stock_user`, `account.group_account_invoice`, `base.group_partner_manager`). Пароль пустой — единственный вход через API key.

### 3.7 Что мы НЕ используем

- **Polling.** Будет fallback safety-net (cron в middleware: `search_read sale.order where write_date > cursor`). Latency = poll interval, нагрузка на Odoo. Только если webhook delivery упадёт.
- **PG LISTEN/NOTIFY.** `bus.bus` использует, но требует direct PG connection (PgBouncer transaction-mode не proxy'ит LISTEN). **Не рекомендую** — unsupported для external integrations.
- **`bus.bus` longpolling.** Только для in-app chat. Не нам.

---

## 4. Mapping — Saleor ↔ Odoo

Источники: [Saleor schema](https://docs.saleor.io/api-reference/), [Odoo 19 source](https://github.com/odoo/odoo/tree/19.0).

### 4.1 Product → product.template

| Saleor | Type | Odoo | Type | Identification key | Notes |
|---|---|---|---|---|---|
| `id` | `ID!` (base64) | `product.template.id` | Integer | external mapping | Saleor IDs декодируются как `Product:<int>` |
| `slug` | `String!` | — | — | XMLID suffix | `slug` нет в product.template core (есть в `website_sale`) |
| `name` | `String!` | `name` | `Char(translate=True, required)` | display | Direct |
| `description` | `JSONString` (EditorJS) | `description_sale` | `Text` или `Html` | — | **Mismatch:** Saleor хранит EditorJS JSON, Odoo HTML. Нужен converter |
| `seoTitle`/`seoDescription` | `String` | — | — | — | Не в core; в `website_sale` (`website_meta_title`) |
| `weight` | `Weight {value, unit}` | `weight` | `Float` | — | Unit conversion (Saleor per-value, Odoo global UoM) |
| `productType` | `ProductType!` | — | — | — | Saleor's attribute schema; в Odoo это `attribute_line_ids` |
| `category` | `Category` | `categ_id` | `Many2one(product.category)` | category external map | Direct |
| `channelListings` | `[ProductChannelListing]` | `pricelist_item_ids` (если multi-channel) | — | (template, pricelist) | **Mismatch:** Saleor channel ~= Odoo pricelist |
| `variants` | `[ProductVariant]` | `product_variant_ids` | `One2many(product.product)` | — | |
| `thumbnail` | `Image` | `image_1920` (+ computed 1024/512/256/128) | `Image` | — | Saleor URL, Odoo binary; expose через `/web/image/` |
| `media` | `[ProductMedia]` | `product_document_ids` | `One2many(product.document)` | — | Image gallery — в `website_sale` |
| `defaultVariant` | `ProductVariant` | `product_variant_id` (computed, only single-variant case) | — | — | |
| `created`/`updatedAt` | `DateTime!` | `create_date`/`write_date` | `Datetime` | — | UTC |

**Identification.** XMLID `saleor_sync.product_template_<saleor_int>`. Обратно — `Product.externalReference` хранит Odoo ID. Slug — мутируем в Saleor, не годится как primary key.

### 4.2 ProductVariant → product.product

| Saleor | Type | Odoo | Type | Notes |
|---|---|---|---|---|
| `id` | `ID!` | `id` | Integer | XMLID `product_product_<saleor_int>` |
| `sku` | `String` | `default_code` | `Char` | **Strong natural key** для upsert |
| `name` | `String!` | `display_name` (computed) | — | "Size: L / Color: Red" — Odoo собирает из template + PTAV |
| `attributes` | `[AssignedAttribute]` | `product_template_attribute_value_ids` | `Many2many(PTAV)` | Readonly на variant; меняется через template |
| `channelListings` | `[ProductVariantChannelListing]` | `lst_price` + `product.pricelist.item` per variant | `Float` + `One2many` | **Major mismatch:** Saleor per-variant per-channel price, Odoo per-variant delta через PTAV `price_extra`. Для per-channel — `pricelist.item` rows |
| `stocks` | `[Stock]` | `stock.quant` per (product, location) | — | See §4.11 |
| `weight` | `Weight` | `weight` | `Float` | Override template weight |
| `trackInventory` | `Boolean!` | `product.template.is_storable` | `Boolean` | **Mismatch:** Saleor per-variant toggle, Odoo per-template |
| `product` | `Product!` | `product_tmpl_id` | `Many2one` | |

### 4.3 Attribute / AttributeValue → 4-уровневая Odoo модель

Odoo тратит 4 таблицы для variant attributes:

1. **`product.attribute`** — глобальная дефиниция атрибута ("Color"). `create_variant` ∈ `always`/`dynamic`/`no_variant`.
2. **`product.attribute.value`** — глобальный pool значений ("Red", "Blue"), `Many2one → product.attribute`.
3. **`product.template.attribute.line`** (PTAL) — junction "template X использует attribute Y с этими значениями".
4. **`product.template.attribute.value`** (PTAV) — материализованный per-template per-value record. На нём `price_extra`. Автогенерируется из PTAL.

**Sync mechanic:**

```
1. Ensure product.attribute + product.attribute.value exist (global).
2. Create/update product.template.attribute.line на template
   с references на attribute + selected values.
3. Odoo автоматически создаёт PTAV rows и (если create_variant='always')
   cross-product product.product variants.
4. Map Saleor ProductVariant.attributes на PTAV by lookup
   (attribute_id, product_attribute_value_id).
```

| Saleor | Type | Odoo | Notes |
|---|---|---|---|
| `Attribute.id` | `ID!` | `product.attribute.id` | XMLID `product_attribute_<id>` |
| `Attribute.name` | `String!` | `name` | Translatable |
| `Attribute.inputType` | `DROPDOWN/MULTISELECT/BOOLEAN/NUMERIC/RICH_TEXT/DATE/FILE/REFERENCE/SWATCH` | `display_type` ∈ `radio/select/color/pills` | **Major mismatch:** Saleor range шире. Non-choice (RICH_TEXT, FILE, REFERENCE) — без Odoo equivalent, в Properties field или x_ custom |
| `Attribute.choices` | `[AttributeValue]` | `value_ids` | One2many |
| `AttributeValue.name` | `String!` | `name` | |
| `AttributeValue.value` (HEX swatch) | `String` | `html_color` | |
| `AttributeValue.slug` | `String!` | — | В XMLID |

### 4.4 Category → product.category

| Saleor | Odoo | Notes |
|---|---|---|
| `id` | `id` | XMLID |
| `name` | `name` | Translatable |
| `slug` | — | В XMLID |
| `parent` | `parent_id` | |
| `level` | derive from `parent_path` | |
| `children` | `child_id` | |
| `description` (EditorJS) | — в core | Custom field или `website_sale.product.public.category` |
| `backgroundImage`, `seoTitle`, `seoDescription` | — в core | `website_sale` territory |

Sync — топологический порядок (parents before children).

### 4.5 Customer (User) → res.partner

| Saleor | Odoo | Notes |
|---|---|---|
| `id` | `id` | XMLID `res_partner_<saleor_int>` |
| `email` | `email` | **Strong natural key** для дедупа (case-insensitive) |
| `firstName` + `lastName` | `name` (concat) | **Mismatch:** Saleor split, Odoo merged. Записываем `"<first> <last>"` |
| `isActive` | `active` | |
| `addresses` | `child_ids` где `type ∈ invoice/delivery/other` | See §4.6 |
| `defaultBillingAddress` | (нет FK) | Odoo вычисляет через `child_ids` + `type='invoice'`. Опционально custom field `default_billing_address_id` |
| `defaultShippingAddress` | (то же с `type='delivery'`) | |
| `languageCode` | `lang` | `EN_US` → `en_US` lookup |
| `dateJoined` | `create_date` | |
| `lastLogin` | `res.users.login_date` (если portal user) | На users, не partner |
| `orders` (reverse) | reverse of `sale.order.partner_id` | |

Set `customer_rank > 0` чтобы partner появлялся как customer в sale flow.

### 4.6 Address → res.partner (child)

**Pattern:** Один Saleor `User` с N addresses → один parent `res.partner` (customer) + N child `res.partner` через `parent_id`, каждый с `type` ∈ `'invoice'`/`'delivery'`/`'other'`/`'contact'`.

| Saleor Address | Odoo res.partner (child) | Notes |
|---|---|---|
| `firstName` + `lastName` | `name` (concat) | |
| `companyName` | `commercial_company_name` или `name` с `is_company=True` | |
| `streetAddress1` | `street` | |
| `streetAddress2` | `street2` | |
| `city` | `city` | |
| `cityArea` | — в core | `base_address_extended` модуль или в `street2` |
| `postalCode` | `zip` | |
| `country` (`CountryDisplay`) | `country_id` (lookup by `code` ISO-2) | |
| `countryArea` | `state_id` (lookup by `(country_id, code)`) | Может потребоваться lookup table |
| `phone` | `phone` | |

XMLID `res_partner_addr_<saleor_addr_int>`. Set `parent_id` и `type` всегда вместе.

### 4.7 Order → sale.order

| Saleor | Odoo | Notes |
|---|---|---|
| `id` | `id` | XMLID `sale_order_<saleor_int>` |
| `number` | `client_order_ref` (preserves Saleor sequence) | Не `name` — Odoo generates own sequence |
| `user` | `partner_id` | См. §4.5 |
| `billingAddress` | `partner_invoice_id` | resolves via §4.6 |
| `shippingAddress` | `partner_shipping_id` | |
| `lines` | `order_line` | See §4.8 |
| `shippingPrice` | dedicated `sale.order.line` (с shipping product) | **Mismatch:** Saleor single field, Odoo — order line. `delivery` модуль добавляет `carrier_id` |
| `total` | `amount_total` (computed) | Не пишем напрямую |
| `subtotal` | `amount_untaxed` | Saleor subtotal excludes shipping; verify per channel |
| `status` | `state` (`draft`/`sent`/`sale`/`cancel`) | **Mismatch:** Saleor splits sales+fulfillment; Odoo splits sale state + picking state |
| `paymentStatus` | `invoice_status` + `account.move.payment_state` | Multi-step (invoice + payment) |
| `channel` | `team_id` или `warehouse_id` или `pricelist_id` или `company_id` | **Mismatch:** Saleor channel = first-class boundary. Convention: 1 channel = (company, warehouse, pricelist) tuple |
| `created` | `date_order` | |
| `voucher` | discount lines или `client_order_ref` extension | |
| `discounts` | `order_line.discount` (% per line) | **Mismatch:** Saleor order-level discount → разнести по lines |

### 4.8 OrderLine → sale.order.line

| Saleor | Odoo | Notes |
|---|---|---|
| `id` | `id` | XMLID |
| `variant` | `product_id` | |
| `productName` + `variantName` | `name` (Odoo merges product + variant + custom text) | |
| `productSku` | `product_id.default_code` (related) | |
| `quantity` | `product_uom_qty` | Saleor Int, Odoo Float |
| `unitPrice.gross/.net` | `price_unit` (always tax-excl) | **Mismatch:** Saleor returns both, Odoo считает `price_total` из `tax_ids` |
| `totalPrice` | `price_subtotal` (excl) / `price_total` (incl) | computed |
| `taxRate` | `tax_ids` (на `account.tax.amount`) | **Mismatch:** Saleor flat rate, Odoo tax record. Lookup или create `account.tax` |
| discount % | `discount` | Compute from `unitPrice` vs `undiscountedUnitPrice` |

### 4.9 Payment / TransactionItem → account.payment + account.move

**Полный flow "order is paid":**

```
1. sale.order.action_confirm()              # draft → sale, генерит picking
2. sale.order._create_invoices()            # → account.move (out_invoice, draft)
3. account.move.action_post()               # draft → posted
4. account.payment.register({...invoice})   # wizard, then action_create_payments()
5. invoice.payment_state → paid / in_payment / partial   # автоматически
```

| Saleor TransactionItem | Odoo | Notes |
|---|---|---|
| `id` | `account.payment.id` | XMLID |
| `pspReference` | `account.payment.payment_reference` | **Strong natural key** |
| `name` | `memo` | |
| `chargedAmount` | `amount` (с `payment_type='inbound'`) | |
| `refundedAmount` | отдельный `account.payment` с `payment_type='outbound'` | Refunds — свои записи |
| `canceledAmount` | `state='canceled'` | |
| `actions` | — | UI-driven workflow в Odoo |
| `events` | `mail.message` history | **Mismatch:** Saleor structured event log, Odoo chatter |
| `paymentMethodDetails` | `payment_method_line_id` + `journal_id` | Map Saleor PSP name → Odoo `account.payment.method.line` |
| Order-level `paymentStatus` | `account.move.payment_state` | Computed |

### 4.10 Warehouse → stock.warehouse

| Saleor | Odoo | Notes |
|---|---|---|
| `id` | `id` | XMLID |
| `name` | `name` | |
| `slug` | `code` (≤5 chars unique per company) | **Mismatch:** Saleor long-form slug, Odoo 5-char prefix. Truncate/hash |
| `email` | `partner_id.email` | |
| `address` | `partner_id` | Create partner для warehouse |
| `shippingZones` | `delivery.carrier` + `account.fiscal.position` | **Mismatch:** Saleor связывает страны с carriers, Odoo разделяет |
| `clickAndCollectOption` | — | **Not found** |

Warehouse — create-once: Odoo автоматически создаёт `stock.location`, `stock.picking.type`, `stock.route` при создании; rename `code` rewrite picking-type sequences.

### 4.11 Stock → stock.quant (с большим *)

| Saleor Stock | Odoo | Notes |
|---|---|---|
| `id` | `stock.quant.id` | **Volatile**, key — `(product_id, location_id)` |
| `warehouse` | `quant.location_id` → walk to `warehouse_id` через `stock.location` | Resolve to `warehouse.lot_stock_id` |
| `productVariant` | `quant.product_id` | |
| `quantity` | `quant.quantity` | **CRITICAL:** **readonly!** Не писать напрямую |
| `quantityAllocated` | `reserved_quantity` (readonly) | Computed by reservations |
| `quantityReserved` | overlaps `reserved_quantity` | **Mismatch:** Saleor splits checkout vs order reservations, Odoo один bucket |

**Как менять остатки правильно** (mandatory):

**Path A — inventory adjustment** (для one-off resyncs):
```python
quant.write({'inventory_quantity': new_qty})
quant.action_apply_inventory()
```

**Path B — stock.move** (для live increments):
```python
move = env['stock.move'].create({
    'name': 'Saleor sync', 'product_id': pid,
    'location_id': inventory_loss_loc_id, 'location_dest_id': stock_loc_id,
    'product_uom_qty': delta,
    'origin': f'saleor-sync-{run_id}',
})
move._action_confirm(); move._action_assign()
move.move_line_ids.write({'quantity': delta})
move._action_done()
```

Прямой `quant.write({'quantity': X})` → `UserError`.

**Идемпотентность** на move path: `origin` поле кодирует sync run, retried webhook = no-op duplicate, фильтруем по `origin`.

### 4.12 Cross-cutting concerns

**Currency.** Saleor `Money {amount, currency: ISO3}`; каждый priced object несёт свою. Odoo `Monetary` всегда с `currency_id: Many2one(res.currency)`. Lookup: `search([('name','=', code)])`. Channel pricelist/company должны иметь матч-currency, иначе Odoo silently converts через `res.currency.rate_ids`.

**Tax.** Saleor: channel-level toggle (`Channel.taxConfiguration.pricesEnteredWithTax`); каждая OrderLine содержит и `gross` и `net` + `taxRate: Float`. Odoo: per-tax property (`account.tax.price_include`); каждая `sale.order.line` имеет `tax_ids: Many2many(account.tax)`. **Pre-create `account.tax`** для каждой rate × jurisdiction. Resolve на write через `(amount, type_tax_use='sale', company_id)`.

**Time zones.** Saleor — UTC ISO-8601 с `Z`. Odoo — naive UTC в DB, конвертится в UI. Parse Saleor → strip tz → naive UTC → write.

**Translations.** Saleor — `translation(languageCode)` resolver. Odoo — `translate=True` на field; JSON storage. Write через `with_context(lang='xx_YY')`. Saleor lang codes (`RU`, `EN_US`) → `res.lang.code` (`ru_RU`, `en_US`) — lookup table.

**Rich text / HTML.** Saleor — EditorJS JSON `{blocks: [{type, data}, ...]}`. Odoo — sanitized HTML. Нужен **EditorJS → HTML serializer** (paragraph → `<p>`, header N → `<hN>`, list → `<ul>/<ol>`, etc.). Reverse direction lossy → выбираем одну source-of-truth и replicate.

**External ID strategy.**
- **Saleor side:** `externalReference` поле на `Product`, `ProductVariant`, `Warehouse`, `User`, `Order`, `OrderLine` — туда пишем Odoo integer ID.
- **Odoo side:** `ir.model.data` rows с `module='saleor_sync'`, `name='<entity>_<saleor_int>'`, `res_id=<odoo_id>`. Lookup через `env.ref('saleor_sync.product_template_42', raise_if_not_found=False)`.

Saleor IDs декодируются `base64decode("UHJvZHVjdDox") = "Product:1"` — стрипаем prefix, integer — наш XMLID suffix.

---

## 5. Архитектурные опции

### Option A (РЕКОМЕНДУЮ): Saleor App + Odoo custom module

```
        ┌────────────────┐                ┌──────────────────────┐
        │  Saleor 3.23   │                │  Saleor App          │
        │  (self-hosted) │  webhook       │  (Next.js + TS)      │
        │                │ ────────────▶  │  hosted on Vercel    │
        │  • Orders      │   JWS signed   │  or self-hosted      │
        │  • Customers   │                │                      │
        │  • Catalog     │  GraphQL       │  - HMAC/JWS verify   │
        │  • Stock       │ ◀────────────  │  - dedupe by id+hash │
        └────────────────┘   App token    │  - enqueue (Redis)   │
                                          │  - worker → JSON-2   │
                                          └───────┬──────────────┘
                                                  │ POST /json/2/...
                                                  │ Authorization: bearer
                                                  ▼
                                          ┌──────────────────────┐
                                          │  Odoo 19 Community   │
                                          │                      │
                                          │  + saleor_sync       │
                                          │    custom module:    │
                                          │    - mappers         │
                                          │    - ir.model.data   │
                                          │    - server actions  │
                                          │      (webhook out)   │
                                          │    - queue_job       │
                                          └──────────────────────┘
                                                  │
                                                  │ ir.actions.server
                                                  │ state='webhook'
                                                  │ POST stocks/status
                                                  ▼
                                          ┌──────────────────────┐
                                          │  Saleor App          │
                                          │  /api/odoo/incoming  │
                                          └──────┬───────────────┘
                                                 │ GraphQL mutation
                                                 ▼
                                          ┌──────────────────────┐
                                          │  Saleor 3.23         │
                                          └──────────────────────┘
```

**Tech stack:**
- **Saleor App:** TypeScript, Next.js 14+ (App Router), `@saleor/app-sdk` 1.0+, deploy on Vercel или self-hosted (как у нас уже storefront). APL — Redis или Postgres (можно использовать существующую Saleor DB через отдельную schema).
- **Очередь:** Redis Streams внутри App для webhook-ack queue, плюс `queue_job` внутри Odoo для тяжёлой работы.
- **Odoo:** custom module `saleor_sync` (Python, LGPL-3 чтобы можно было OCA-публиковать позже).
- **Деплой:** App = Vercel или Docker compose рядом с saleor. Odoo — уже наш self-hosted.

**Pros:**
- Канонический Saleor pattern (saleor/apps monorepo doing same).
- Odoo 19 native webhook server action + JSON-2 минимизируют custom-код в Odoo.
- queue_job даёт retry/dedup/concurrency control из коробки.
- Можем зарегистрировать App в Saleor Marketplace позже (commercial opportunity).
- Изоляция: middleware падает — Odoo работает; Odoo down — webhooks буферизируются в App's Redis.

**Cons:**
- Два runtime'a (TS + Python). Команда должна знать оба.
- Saleor App требует public URL (для webhook delivery) — нужен deploy / tunneling.
- Lock-in в Saleor App framework (нельзя легко свитчнуть на другую e-com platform).

**Сложность реализации:** ~76 часов до production (см. §1).
**Сложность поддержки:** Medium. Два кода-бейза. Но каждая часть тонкая (1000-3000 LOC).

### Option B: Pure Python middleware (без Saleor App)

```
        ┌────────────────┐                ┌──────────────────────┐
        │  Saleor 3.23   │   webhook      │  FastAPI middleware  │
        │                │ ────────────▶  │  (Python)            │
        │                │                │                      │
        │                │   GraphQL      │  - poll Saleor       │
        │                │ ◀────────────  │    (no App, plain    │
        │                │                │    bearer token)     │
        │                │                │  - HMAC verify       │
        │                │                │  - poll Odoo for     │
        │                │                │    write_date deltas │
        └────────────────┘                │  - JSON-2 → Odoo     │
                                          └──────────┬───────────┘
                                                     │
                                                     ▼
                                          ┌──────────────────────┐
                                          │  Odoo 19 Community   │
                                          │  (без custom module) │
                                          └──────────────────────┘
```

**Tech stack:** Python, FastAPI, `httpx`, Celery/Dramatiq + Redis, без Odoo-side module.

**Pros:**
- Один runtime (Python — наш уже есть в payments).
- Никакой Saleor App registration головной боли.
- Outbound из Odoo через polling — нет required custom module.
- Проще для local dev.

**Cons:**
- **Polling Odoo дороже** (нагрузка + latency). На каждый stock update — N запросов в Odoo каждые M секунд.
- **Нет App'овского signature verification** — придётся вручную писать JWS/HMAC.
- **Outbound Saleor → Odoo через webhook'ы без App** — Saleor требует, чтобы receiver был "registered webhook" с подпиской. Можно создать webhook напрямую через GraphQL `webhookCreate`, но это вне App-flow и без Dashboard UI.
- Полностью кастомное решение — никаких саппорт-конвенций.

**Сложность реализации:** ~60 часов (меньше, но без mature framework).
**Сложность поддержки:** High. Polling = больше кода + edge cases (cursor lost, double-fetch, missed events).

### Option C: ETL no-code (n8n / Airbyte / Meltano)

**Reality check** ([§6](#6-existing-landscape--что-уже-сделано)):
- **n8n:** Odoo node (XML-RPC) есть, **Saleor node — НЕТ** (ни official, ни community visible). Любая Saleor↔Odoo синка через n8n = hand-rolled HTTP/GraphQL workflows.
- **Airbyte:** Odoo connector ([airbytehq/airbyte-connectors](https://github.com/airbytehq/airbyte)) есть, **Saleor connector — НЕТ**.
- **Meltano:** No Saleor tap.

→ **Option C мёртв.** Минимум half работы — написать кастомные коннекторы для каждой ноды, что эквивалентно Option B без преимуществ.

**Не рекомендую.**

### Option D: Использовать `OCA/connector` framework

OCA/connector — generic Odoo-side framework для коннекторов (jobs queue, async tasks, channels, components, mapping). Используется в `connector-magento`, `connector-prestashop`, `connector-woocommerce`.

**Реалии (май 2026):**
- [`OCA/connector`](https://github.com/OCA/connector) — **18.0 latest** branch (1,121 commits на 18.0). **19.0 branch ещё не портирован**.
- `OCA/connector-ecommerce` — 18.0, 3 commits, lightly maintained.
- `OCA/connector-shopify` — не существует.

**Не рекомендую сейчас** — придётся либо ждать 19.0 порт, либо самому портировать (high risk). Option A через `queue_job` (который portирован на 19.0) даёт 80% бенефита connector framework без зависимости.

**Если/когда** OCA сделает 19.0 порт — можно мигрировать `saleor_sync` под него.

### Сводная таблица

| Критерий | A (Saleor App + Odoo module) | B (Pure middleware) | C (n8n/Airbyte) | D (OCA connector) |
|---|---|---|---|---|
| **Канон** | Yes (Saleor pattern) | Custom | No | Yes (Odoo) but no 19 yet |
| **Кода писать** | ~3000 LOC TS + 2000 LOC Python | ~4000 LOC Python | ~5000 LOC custom nodes | ~3000 LOC Python |
| **Runtime'ов** | 2 (TS + Python) | 1 (Python) | 1 (workflow engine) | 1 (Python) |
| **Retry/dedupe из коробки** | Yes (`queue_job`, App SDK) | No, писать руками | Partial | Yes |
| **Saleor signature** | Yes (App SDK) | Manual | Manual | Manual |
| **Odoo native webhook** | Yes | Polling only | Polling | Yes |
| **Сложность реализации** | Medium (76ч) | Medium-High (60-90ч) | High (написать коннекторы 100+ч) | Blocked (no 19) |
| **Поддержка** | Medium | High | Medium | Medium |
| **Marketplace upside** | Yes (можно ship'ить в Saleor App Store) | No | No | No |

**Вердикт: Option A.**

---

## 6. Existing landscape — что уже сделано

### 6.1 Saleor ↔ Odoo напрямую

**Не нашёл ничего production-grade.**

Поиск:
- GitHub `saleor odoo` / `odoo-saleor` / `saleor connector odoo` — zero repos с обоими словами в name/description.
- Saleor App Store ([apps.saleor.io](https://apps.saleor.io/)) — категории: payments, taxes, CMS, automation. **ERP-категории нет вообще.** Никаких Odoo/NetSuite/SAP/Dynamics.
- OCA — нет `connector-saleor`.
- Saleor core [issue #3033 "Odoo API Integration"](https://github.com/saleor/saleor/issues/3033) — открыт октябрь 2018, закрыт без implementation. Единственный задокументированный signal спроса.

→ **Мы первые публично.** Никаких schema mappings, edge-case lists, test fixtures чтобы переиспользовать.

### 6.2 Saleor App patterns

[`saleor/apps`](https://github.com/saleor/apps) — TypeScript monorepo (99.4% TS), Turborepo, PNPM, Next.js, deploy Vercel. 1,405 commits — main reference.

Apps внутри: `avatax`, `cms`, `klaviyo`, `products-feed`, `search`, `segment`, `smtp`, `stripe`, `np-atobarai`.

Pattern:
- Каждый app — отдельный Next.js проект.
- State через **APL (App Persistence Layer)** — swap-in Redis / DynamoDB / file. AvaTax + Segment требуют DynamoDB.
- Webhooks через `@saleor/app-sdk/handlers/next-app-router` с mandatory signature verification (raw body, body parser disabled).
- 21-day минимум package-age, exact-version pinning (supply-chain hygiene).

→ **Это шаблон для нашего Saleor App.**

[`saleor/saleor-app-lambda-template`](https://github.com/saleor/saleor-app-lambda-template) — AWS CDK + Lambda skeleton (если ходим serverless).

[`mirumee/saleor-app-framework-python`](https://mirumee.github.io/saleor-app-framework-python/) — Python alternative, FastAPI + Pydantic. **"Still in development"** — рисково для production.

### 6.3 Odoo connector ecosystem

| Repo | Health | Notes |
|---|---|---|
| [OCA/connector](https://github.com/OCA/connector) | **18.0 active** (1,121 commits), no 19 yet | Generic framework: components, queue, mapping |
| [OCA/connector-ecommerce](https://github.com/OCA/connector-ecommerce) | 18.0 sparse (3 commits) | Lightly maintained |
| [OCA/connector-magento](https://github.com/OCA/connector-magento) | Last release **3.0.0 June 2015**, 66 open issues | Effectively in limbo |
| [OCA/connector-woocommerce](https://github.com/OCA/connector-woocommerce) | 18.0 skeleton, no releases | More skeleton чем product |
| [OCA/connector-prestashop](https://github.com/OCA/connector-prestashop) | 93 stars, only 4 open issues | Best maintained |
| OCA/connector-shopify | **Not found** | Shopify-Odoo рынок owned by commercial vendors |
| [`OCA/queue/queue_job 19.0.2.0.1`](https://github.com/OCA/queue/tree/19.0/queue_job) | **Mature, Odoo 19** | Job queue. Используем. |

**Commercial Odoo↔e-commerce connectors** (заполнили вакуум OCA):
- [VentorTech](https://ecosystem.ventor.tech/) — paid Shopify/WooCommerce/Magento/PrestaShop на shared "Odoo E-Commerce Connector Core". Coordinated release Nov 2025. Claims 1000+ deployments. Closed source.
- Многочисленные "Odoo Shopify Connector PRO/EPT/KS" на apps.odoo.com — paid, closed source.

**Architecture pattern шарится** (synthesized из VentorTech docs):
- Layered architecture в Odoo: transport (HTTP/GraphQL) → mapper → queue model → business model.
- Hybrid sync: webhooks от e-commerce для high-signal events; scheduled cron в Odoo для bulk reconciliation.
- Jobs queue (queue_job) для retry, idempotency, rate-limiting.
- Batch size ~250 для bulk imports — common figure из Shopify connectors.
- Source-of-truth split per entity.

→ **Это playbook для Saleor↔Odoo.** Saleor GraphQL + 160+ webhooks делают его *проще* чем Shopify REST.

### 6.4 Saleor migration playbooks (Shopify, Woo, etc.)

**Not found** Saleor-specific writeups. Поиск `"Saleor" migration playbook` / `Saleor Shopify migration` / `Saleor WooCommerce sync` — results все WooCommerce↔Shopify в другую сторону.

Closest: [Flux's WooCommerce→Shopify Plus playbook](https://flux.agency/insights/migrating-woocommerce-to-shopify-plus-complete-playbook) — useful только для generic data-modeling раздела.

### 6.5 ERP↔e-commerce reference architectures

- [Mirumee Lifesize case study](https://mirumee.com/case-study/lifesize) — Saleor + NetSuite. Единственное архитектурное предложение: *"Orders are only kept in Saleor; users are saved to their API/ERP."* Подтверждает что split source-of-truth per entity — legit pattern.
- [Mirumee Saleor App Framework docs](https://mirumee.github.io/saleor-app-framework-python/) — generic "AWS Lambda + API Gateway listening to Saleor webhooks → forward to ERP" pattern.
- VentorTech docs — generic ERP↔e-commerce architectural patterns (но платформа wrong).

**Не нашёл** Saleor↔ERP post-mortems или conference talks.

### 6.6 Saleor App Store запись для Odoo

**Not found.** Подтверждено через прямой list App Store. **Если ship'нем — нет конкуренции в slot'е.**

### Bottom line для архитектуры

1. **No prior art для reuse / fork / learn.** Plan greenfield.
2. **Architecture cribs from VentorTech-style internal layering** (queue_job + hybrid webhooks-plus-cron) на Odoo side. Не моделировать project shape на OCA-connectors (dormant).
3. **Saleor side следует `saleor/apps` conventions** — TypeScript + Next.js + `@saleor/app-sdk`. Diverge только с justification.
4. **Source-of-truth split = load-bearing decision.** Mirumee precedent (orders in Saleor, customers in ERP) — один sane default; Shopify↔Odoo norm (products+inventory authored in Odoo, orders mirrored both ways) — другой. Решаем per entity и documentируем.
5. **Schema mapping изобретаем сами.** Public catalog Saleor↔Odoo field mappings does not exist. Budget time на mapping doc до code (этот документ — уже шаг 1).

---

## 7. Open questions для заказчика

### Q1. Channels — один или несколько?

Сейчас один: `default-channel` (UZS).

Варианты:
- **A. Один channel (status quo).** Простая модель. Цены/языки одни. Mapping: 1 channel ↔ 1 (company, warehouse, pricelist).
- **B. Multi-channel UZ + RU.** Цены и переводы per channel. Mapping: 2 channels ↔ 2 pricelists в Odoo. Более сложная синка `ProductVariantChannelListing`.
- **C. Multi-channel B2C + B2B (опт).** Разные базы клиентов, разные цены, возможно — разные warehouses.

**Влияет на:** product sync code (одна или N итераций `productVariantChannelListingUpdate`), pricelist setup в Odoo, Saleor permissions.

**Моя рекомендация:** **MVP — один channel.** Multi-channel — Phase 4 после стабилизации.

### Q2. Real-time vs eventual consistency

Какая допустимая задержка стока на витрине?

- **Real-time (<1s):** требует sync webhook или WebSocket. Дорого. Не реалистично с Saleor.
- **Near real-time (1-30s):** async webhook + queue. **Default нашей архитектуры.**
- **Batch (1-5 min):** cron polling. Cheap, latency очевидна клиенту.
- **Slow (>5 min):** не подходит для онлайн-продаж — stockout risk.

**Моя рекомендация:** **Target 5-15s.** Stock change в Odoo → server action → middleware → Saleor mutation. Реалистично с queue_job.

### Q3. Conflict resolution

Если кто-то изменил Product в Saleor Dashboard (хотя не должен — Odoo source-of-truth) — что делать?

- **A. Odoo всегда побеждает.** Следующий sync затирает Saleor change.
- **B. Logging only.** Detect, лог, не трогаем — admin разбирается вручную.
- **C. Bidirectional sync.** Меняем Odoo обратно из Saleor. **Сильно сложнее, не рекомендую.**

**Моя рекомендация:** **A с логом B.** Odoo всегда побеждает, но при detected divergence пишем `mail.message` на product (chatter notification) — админ видит "Saleor name diverged from Odoo at <time>: '<saleor>' vs '<odoo>'".

### Q4. Order flow — когда создавать sale.order в Odoo?

Saleor lifecycle: `Checkout` → `ORDER_CREATED` (placed) → `ORDER_CONFIRMED` (admin confirmed in Dashboard) → `ORDER_PAID` / `ORDER_FULLY_PAID` → `ORDER_FULFILLED`.

Варианты создать sale.order:
- **A. `ORDER_CREATED`** — sale.order в state `draft`. Operator видит unconfirmed orders. Минус: cancelled orders засоряют draft pool.
- **B. `ORDER_CONFIRMED`** — sale.order в state `draft` (Odoo требует draft → action_confirm). Minus: дублируем confirmation двух систем.
- **C. `ORDER_PAID`** — sale.order сразу в `sale`. Минус: операционно видишь только paid (но это часто желаемо для маркетплейса).

**Моя рекомендация:** **A для visibility + C для confirmation.** Создавать sale.order в draft на ORDER_CREATED, вызывать `action_confirm()` на ORDER_PAID/FULLY_PAID. Cancelled orders в Saleor → `_action_cancel()` в Odoo.

### Q5. Возвраты

Saleor умеет:
- Cancel order (`ORDER_CANCELLED`).
- Partial refund (`ORDER_REFUNDED`, не fully).
- Full refund (`ORDER_FULLY_REFUNDED`).
- Return product без refund (manual fulfillment reverse).

Odoo:
- Cancel `sale.order` — `_action_cancel()`.
- Refund — отдельный `account.move` (`out_refund`) + reverse `account.payment` (outbound).
- Return product — отдельный `stock.picking` reverse.

**Открытые вопросы:**
- Партикл refund: refund line ↔ stock return обязателен или sometime money-only refund?
- Refund инициируется в Saleor (admin Dashboard) или в Odoo?

**Моя рекомендация:** **MVP — только cancel + full refund.** Partial refund + return — Phase 3.6.

### Q6. Inventory primary key

SKU (`default_code` / `sku`) или внутренний Odoo ID?

- **SKU как primary:** human-readable, перенесётся при миграции, риск SKU collision.
- **Internal ID:** stable across renames, требует external mapping table.

**Моя рекомендация:** **SKU как natural key, Odoo ID как fallback.** Mapping таблица всегда есть (ir.model.data). Если SKU отсутствует — fall back to XMLID.

### Q7. Failed sync handling

После 5 retry'ев заказ не залетел — что делать?

- **A. Email админу + dashboard.** Никакого автоматического action.
- **B. Email клиенту "сорри есть проблема".** Может быть страшнее чем silence.
- **C. Auto-cancel и refund.** Хорошо для UX, плохо если проблема transient.

**Моя рекомендация:** **A.** Email + Slack alert + dashboard на admin panel с "stuck jobs". Клиента не уведомляем (мы починим в течение часа обычно).

### Q8. Customers per channel

Если будет multi-channel — клиент покупает и в UZ и в RU. Один `res.partner` или два?

- **A. Один partner, multi-company.** Простая cross-channel аналитика. Лучшее для маркетплейса.
- **B. Per-channel partner.** Изоляция. Хуже для customer history.

**Моя рекомендация:** **A.** Один `res.partner` per email, channel хранится на sale.order (через `team_id` или custom field).

---

## 8. Risks и mitigations

### R1. Eventual consistency / oversell на стоке

**Probability:** High (особенно на горячих SKU).
**Impact:** Negative customer experience — продали, не можем отгрузить, refund.

**Scenarios:**
- Saleor показывает qty=1, два клиента одновременно checkout — оба ORDER_CREATED, в Odoo минус 2.
- Odoo бекофис списал товар (manual inventory adjustment) — stock не успел уехать в Saleor.

**Mitigation:**
- **Saleor stock reservation** — `ProductVariant.trackInventory=True`, Saleor reserves stock на checkout (`quantityReserved`). Default behavior, надо подтвердить включён.
- **Safety buffer:** показывать клиенту `MAX(qty - 1, 0)`. Loss = 1 единица на SKU.
- **Outbox pattern** на Odoo side — изменение `stock.quant` через `stock.move` → server action → middleware. Synchronous-ish (<5s).
- **Periodic full reconciliation** — раз в сутки cron: bulk read Saleor stocks vs Odoo `qty_available`, log diffs.

Полностью убрать без переноса source-of-truth в Saleor — невозможно.

### R2. Saleor webhook timeout 20s, реалистично ≤2s

**Probability:** High при нагрузке.
**Impact:** Saleor решит что delivery failed → retry → дубликаты event'ов.

**Mitigation:**
- Webhook handler: HMAC verify → enqueue → return 200. **Не более 200ms на handler.** Реальная работа уходит в queue_job.
- Идемпотентность на receiver (см. §2.2 delivery guarantees).
- Health check endpoint в App, Saleor может его дёрнуть pre-webhook.

### R3. Saleor rate limits (production не документированы)

**Probability:** Medium при bulk operations (catalog re-sync).
**Impact:** 429 errors, partial sync.

**Mitigation:**
- Bulk operations через `productBulkCreate` / `productVariantBulkCreate` — лимит 100 на запрос (best practice).
- Throttling в queue_job channel: `root.saleor_bulk:1` (один worker для bulk).
- Exponential backoff на 429 в middleware.
- Если Saleor self-hosted (наш случай) — no rate limit, но Postgres bottleneck. Monitor `pg_stat_activity`.

### R4. Odoo workers конкурируют за блокировки при bulk write

**Probability:** Medium при concurrent catalog sync.
**Impact:** `SerializationFailure`, transient errors, retry storms.

**Mitigation:**
- Один queue_job worker для catalog mutations (`channel='root.catalog:1'`).
- `identity_key` на jobs — несколько webhooks для одного product = одна job.
- `with_context(tracking_disable=True, mail_create_nolog=True)` чтобы убрать chatter overhead и contention на `mail.message`.
- Используем pricelist updates через `update_or_create` patterns, не bulk delete+create.

### R5. Возврат пользователя после оплаты (success/cancel callback)

**Probability:** Affects 100% of orders.
**Impact:** UX critical — если callback теряется, клиент видит "что-то пошло не так" после успешной оплаты.

**Mitigation:**
- Payments service у нас уже есть (`payments/`, FastAPI). Платёж независим от Saleor↔Odoo sync.
- `ORDER_FULLY_PAID` event приходит из Saleor только когда payment service установил `mark_order_as_paid` (см. `payments/saleor_client.py`).
- Storefront/Mini App listens на payment service callback, redirects клиента — не зависит от Odoo sync.

### R6. Тестовая среда — где тестировать webhooks?

**Probability:** Daily during development.
**Impact:** Слишком медленный feedback loop = больше bugs.

**Options:**
- **A. ngrok / Cloudflare Tunnel.** Local dev Saleor App доступен публичному Saleor через tunnel. Pros: free, instant. Cons: random URL без paid plan.
- **B. Separate Saleor staging instance.** Запустить второй Saleor через docker-compose с другим port. Setup тяжелее, но 100% контроль.
- **C. Saleor Cloud Sandbox.** Бесплатно для dev. Pros: stable URL. Cons: не наш кастомный Saleor 3.23, могут быть schema diffs.

**Моя рекомендация:** **A (ngrok) для прототипа + B (local docker) для CI/integration tests.**

### R7. Развёртывание middleware: zero-downtime для прода

**Probability:** Каждый deploy.
**Impact:** Lost webhooks during deploy window = lost orders.

**Mitigation:**
- Saleor сам ретраит 5 раз с backoff 10s→160s. Если deploy <5 минут — потерь нет.
- Buffer на queue side: запускать новую версию, дождаться draining queue, отключить старую.
- Health check + readiness probe (Kubernetes-style) если перейдём на K8s.
- Vercel handles automatically (atomic deployments).

### R8. API key rotation Odoo (3-месяц TTL)

**Probability:** Раз в 3 месяца.
**Impact:** Sync ломается до ротации.

**Mitigation:**
- Календарь reminder за 2 недели до expiry.
- Document процедуру в runbook (`docs/runbooks/odoo-api-key-rotation.md`).
- Long-term: build admin UI в Saleor App для ротации.

### R9. Saleor 4.0 breaking changes (legacy HMAC уйдёт)

**Probability:** Когда выйдет 4.0 (timeline неизвестен).
**Impact:** Существующий `storefront/app/api/webhooks/saleor/categories/route.ts` сломается, наша новая `saleor_sync` App — нет (использует JWS).

**Mitigation:**
- Новые webhooks делать через JWS с самого начала.
- Legacy categories webhook мигрировать на JWS в Phase 4.

---

## 9. MVP scope — поэтапная раскатка

### Phase 3.0 — Foundation (12 часов)

**Goal:** инфраструктура для всего последующего.

**Scope:**
- Saleor App skeleton: Next.js + `@saleor/app-sdk`, deployment на Vercel или локально через ngrok.
- Manifest endpoint + token-exchange handler.
- Odoo custom module `saleor_sync` skeleton: `__manifest__.py`, depends на `sale_management`, `stock`, `account`, `queue_job`.
- Модель `saleor.binding` — таблица `(model, odoo_id, saleor_id, last_sync)` для external IDs.
- API key создан в Odoo, configured в App env.
- ngrok / public URL для App установлен.
- HMAC/JWS verification working на App side.
- Smoke test: App receives any test webhook, returns 200.

**Не входит:** реальная бизнес-логика sync.

### Phase 3.1 — Saleor → Odoo: orders + customers (12 часов)

**Goal:** заказы из витрины попадают в Odoo.

**Scope:**
- Webhooks: `CUSTOMER_CREATED`, `CUSTOMER_UPDATED`, `ORDER_CREATED`, `ORDER_CONFIRMED`, `ORDER_FULLY_PAID`, `ORDER_CANCELLED`.
- Mappers: User → res.partner (с child addresses), Order → sale.order, OrderLine → sale.order.line.
- Lookup product по SKU (`default_code`).
- Idempotency: external ID + content hash.
- Test: создать заказ через storefront, увидеть в Odoo.

**Не входит:** invoice + payment + accounting; variants (только simple products); refunds.

### Phase 3.2 — Odoo → Saleor: каталог (16 часов)

**Goal:** товары из Odoo появляются в Saleor.

**Scope:**
- Odoo trigger: `base.automation` на `product.template` create/write → `ir.actions.server` (webhook) → middleware.
- Middleware: получить event, fetch product через JSON-2, GraphQL `productCreate` / `productUpdate` в Saleor.
- Categories sync: `product.category` → Saleor `Category` (топологически).
- Initial bulk seed: cron в App `POST /api/odoo/sync-all-products`.
- Без variants — каждый Odoo product → один Saleor product с одним variant.

**Не входит:** variants (Phase 3.5), attributes setup, multi-channel pricing.

### Phase 3.3 — Stock sync Odoo → Saleor (8 часов)

**Goal:** остатки на витрине отражают Odoo.

**Scope:**
- `stock.quant` change → server action → middleware.
- Middleware → Saleor `productVariantStocksUpdate`.
- Mapping: stock.warehouse → Saleor Warehouse (Phase 3.0 seed).
- Periodic full reconcile cron (раз в день): bulk sync stocks Odoo → Saleor.

**Не входит:** reverse direction (Saleor → Odoo на stock не нужно — Odoo source-of-truth).

### Phase 3.4 — Order status Odoo → Saleor (8 часов)

**Goal:** клиент видит "ваш заказ собран / отгружен".

**Scope:**
- Triggers: `sale.order.state` change, `stock.picking.state` change (fulfilled), `account.move.payment_state` change.
- Middleware → Saleor `orderUpdate`, `orderFulfill`, `orderMarkAsPaid` (если ещё нет).
- Cancel из Odoo → Saleor `orderCancel`.

**Не входит:** custom statuses, partial fulfillments.

### Phase 3.5 — Variants + attributes (16 часов)

**Goal:** размер / цвет / etc. работает в обе стороны.

**Scope:**
- Sync `product.attribute` + `product.attribute.value` → Saleor `Attribute` + `AttributeValue`.
- Sync `product.template.attribute.line` → product attribute assignment.
- Каждый `product.product` → отдельный Saleor ProductVariant с attributes.
- Inverse: при ORDER_CREATED resolve variant by SKU + attributes.

**Не входит:** non-choice attributes (RICH_TEXT, FILE).

### Phase 3.6 — Refunds + cancellations (12 часов)

**Goal:** возвраты и отмены работают end-to-end.

**Scope:**
- Saleor `ORDER_REFUNDED` / `ORDER_FULLY_REFUNDED` → Odoo create `account.move` (out_refund) + outbound `account.payment`.
- Saleor `ORDER_CANCELLED` → Odoo `sale.order._action_cancel()` + reverse picking.
- Odoo refund initiated → Saleor `orderRefund`.
- Partial refunds: reverse specific lines.

**Не входит:** insurance / shipping refunds; chargebacks.

### Не в Phase 3 (future)

- Multi-channel (Phase 4).
- Translations sync (Phase 4).
- Promotions / vouchers (Phase 4 — большая отдельная тема).
- Loyalty programs.
- B2B (опт) workflows.
- Marketplace ship из Saleor App Store.

### Cumulative estimates

| Phase | Hours (Claude Code) | Hours (заказчик) | Cumulative Claude |
|---|---|---|---|
| 3.0 | 12 | 2 | 12 |
| 3.1 | 12 | 1 | 24 |
| 3.2 | 16 | 2 | 40 |
| 3.3 | 8 | 1 | 48 |
| 3.4 | 8 | 1 | 56 |
| 3.5 | 16 | 2 | 72 |
| 3.6 | 12 | 2 | 84 |
| **Total to production-ready** | **84** | **11** | |

Plus **Phase 4** (monitoring, deploy automation, hardening): +30-40 hours.

---

## 10. Recommended next step

Конкретные действия. По порядку.

### Принять решения (заказчик, ~30 минут)

- [ ] **Q1 (channels):** один или multi. Моя рекомендация: один для MVP. → влияет на pricelist setup.
- [ ] **Q4 (order flow):** ORDER_CREATED → draft, ORDER_PAID → confirm. Подтвердить.
- [ ] **Q5 (refunds):** MVP только cancel + full refund. Подтвердить.
- [ ] **Q6 (inventory key):** SKU primary. Подтвердить.
- [ ] **Q7 (failed sync):** email + Slack + dashboard. Подтвердить, дать Slack webhook URL для тестов.
- [ ] **Q8 (customers cross-channel):** N/A если один channel.

### Получить доступы (заказчик, ~1 час)

- [ ] **Saleor App token** с permissions: `MANAGE_ORDERS`, `MANAGE_PRODUCTS`, `MANAGE_USERS`, `MANAGE_CHANNELS`. Создать через Saleor Dashboard → Configuration → Apps → "Local apps" → "Create App" (manually) или через GraphQL.
- [ ] **Odoo API key** через Odoo → Preferences → Account Security → New API Key. Срок 3 месяца — записать дату ротации.
- [ ] **ngrok account** (free tier OK) для public URL Saleor App'а в dev.
- [ ] **Slack webhook URL** (для error alerts) — опционально.

### Что я сделаю следующим (assistant)

- [ ] Подготовить промпт для **Phase 3.0** (foundation): создать Saleor App skeleton + Odoo `saleor_sync` module skeleton + ngrok integration.
- [ ] После — промпт для **Phase 3.1** (orders + customers Saleor → Odoo).
- [ ] И так далее по фазам.

Каждый промпт = одна фаза + acceptance criteria + verification steps. Не двигаемся в следующую фазу пока предыдущая не sign'нута.

### Документация для нас

- [ ] Этот документ → reviewed → если апдейты, я обновлю.
- [ ] После Phase 3.0 заведём `docs/runbooks/` с операционными плейбуками (rotation, deployment, monitoring).
- [ ] После Phase 3.6 — `docs/saleor-odoo-architecture.md` финальный, для будущих devs / hires.

---

**Конец документа.**
