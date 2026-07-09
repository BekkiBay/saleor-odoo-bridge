# Runbook — Order lifecycle Odoo ↔ Saleor (Phase 3.4)

Полный жизненный цикл заказа между витриной и backoffice. Дополняет Phase 3.1
(Saleor → Odoo). См. ADR-0019..0022.

## Полная картина направления

```
Saleor (витрина)                         Odoo (backoffice)
────────────────                         ─────────────────
checkout → ORDER_CREATED  ──webhook──▶   sale.order draft           (Phase 3.1)
оплата   → ORDER_FULLY_PAID ─webhook─▶   action_confirm → 'sale'    (Phase 3.1, skip-guard)
                                                │
   UNFULFILLED  ◀───orderConfirm──────  state 'sale'  (Phase 3.4)   ← эта фаза
   FULFILLED + tracking ◀─orderFulfill─  picking 'done' (Phase 3.4) ← эта фаза
   CANCELED  ◀──────orderCancel────────  state 'cancel' (Phase 3.4) ← эта фаза
```

**Событие → мутация** (worker перечитывает состояние из Odoo, ADR-0019):

| Odoo событие | Saleor мутация | Idempotency pre-check |
|--------------|----------------|----------------------|
| sale.order → `sale` | `orderConfirm` | только если статус UNCONFIRMED |
| sale.order → `cancel` | `orderCancel` | skip если CANCELED; refuse если FULFILLED |
| picking → `done` | `orderFulfill` (+ tracking) | skip если FULFILLED |
| manual payment | `orderMarkAsPaid` | skip если уже оплачен |

## Предусловия

1. Phase 3.1/3.2/3.3 работают (заказы создаются Saleor→Odoo, есть catalog + stock).
2. Модуль `saleor_sync` v0.4.0 (order/picking automations):
   ```bash
   docker compose exec odoo odoo -c /tmp/odoo.conf -d marketplace -u saleor_sync --stop-after-init --no-http
   docker compose restart odoo
   ```
3. Saleor App имеет MANAGE_ORDERS (для orderFulfill/Confirm/Cancel) — из Phase 3.0 manifest.

## Операторский flow (типовой заказ)

1. **Покупатель оформил + оплатил** на витрине → заказ автоматически появляется в
   Odoo как `sale.order` в state `sale` (подтверждён). Витрина: UNFULFILLED.
2. **Менеджер собирает заказ** → открывает delivery picking, ставит quantities,
   при наличии — заполняет `carrier_tracking_ref` (трек-номер).
3. **Validate picking** (кнопка «Validate») → state `done`. Через ~5 сек витрина:
   **FULFILLED**, у fulfillment проставлен trackingNumber, клиенту ушёл email
   «заказ отправлен» (`notifyCustomer=True`, ADR-0022).
4. **Отмена** (если нужно): `Cancel` на sale.order → state `cancel` → витрина
   CANCELED. ⚠️ нельзя отменить уже отгруженный (FULFILLED) заказ — это возврат
   (out of scope Phase 3.4); middleware залогирует и не упадёт.

## Reverse-echo guard (ADR-0020) — почему нет петли

Когда Phase 3.1 подтверждает заказ из Saleor-вебхука, он вызывает Odoo
`action_confirm` с `context={'saleor_sync_skip': True}`. Outbound-automation видит
флаг → НЕ эмитит событие обратно. Эхо разорвано. Ручное изменение state в Odoo
(не из Saleor) флага не несёт → пушится на витрину (желаемо).

## Проверка

```graphql
# статус заказа + fulfillments + tracking
query{ order(id:"<ORDER_ID>"){
  number status isPaid paymentStatus
  fulfillments{ id status trackingNumber lines{ quantity orderLine{ productSku } } }
  lines{ productSku quantity quantityFulfilled }
}}
```

```bash
# событие дошло? (Odoo outbox)
# saleor.outbox по sale.order / stock.picking — state confirmed/200
# worker обработал?
docker compose logs --since 2m middleware-worker | grep -E "order_state_synced|picking_synced|order_confirmed|order_fulfilled"
```

## Troubleshooting

| Симптом | Причина | Действие |
|---------|---------|----------|
| Витрина не меняет статус | automation не сработала / нет binding | `saleor.outbox` есть запись? у заказа есть `saleor.binding(sale.order)`? (заказ должен быть из Saleor) |
| `orderConfirm` no-op | заказ уже не UNCONFIRMED | ок, idempotency (норма) |
| Cancel «cannot cancel FULFILLED» | заказ отгружён | это возврат, не отмена (out of scope) — обработай вручную |
| Fulfill «nothing to fulfill» | строки уже зафулфиллены / SKU не совпал | проверь `productSku` в Saleor order == `default_code` в Odoo |
| tracking пустой на витрине | `carrier_tracking_ref` не заполнен в picking | заполни до validate |
| **Дубль/петля статусов** | skip-guard не сработал | проверь что Phase 3.1 confirm/cancel идут с `saleor_sync_skip` context (ADR-0020) |

## Известные ограничения (Phase 3.4)

- **Один полный fulfillment на заказ** (ADR-0021). Частичные/многокоробочные
  отгрузки, backorders — Phase 4.
- **Reverse (`fulfillmentCancel`)** при отмене отгрузки — NO-OP в MVP.
- **Returns** (возвраты из Odoo) и **order edit** (правка строк после confirm) —
  out of scope.
- **notify** контролируется только на `orderFulfill`; confirm/cancel-уведомления —
  по настройкам Saleor (ADR-0022).
