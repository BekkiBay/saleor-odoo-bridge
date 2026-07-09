# Runbook — Stock sync Odoo → Saleor (Phase 3.3)

Синхронизация остатков из Odoo (`stock.quant`) на витрину Saleor. Источник истины
по остатку — Odoo. См. ADR-0015..0018 (и ADR-0010 как базу).

## Архитектура

```
Odoo stock.quant (quantity write)
   │ base.automation (trigger_field=quantity) → ir.actions.server (code)
   │ records._saleor_dispatch_stock(): saleor.outbox + POST per product.product
   ▼
POST {middleware}/api/odoo-events?secret=…   {odoo_model:'product.product', odoo_id:N, action:'write'}
   │ validate secret → enqueue arq (defer ~3s, dedup model+id+5s bucket) → 200
   ▼
arq worker: sync_odoo_record_to_saleor → ветка product.product → sync_stock_to_saleor
   1. product.product → product_tmpl_id → saleor.binding(product.template) → Saleor product
   2. Saleor product → variants[0].id
   3. ensure_warehouse (get-or-create, ADR-0015)
   4. агрегат internal-quant'ов + safety buffer (ADR-0016)
   5. trackInventory=True + productVariantStocksUpdate
   6. touch saleor.binding.last_sync_out
```

**Ключевое:** субъект события — `product.product`, а не сам quant. Worker
перечитывает текущий агрегат остатка из Odoo (устойчиво к гонкам и удалённым
quant'ам, ADR-0017).

## Предусловия

1. Каталог уже засеян (Phase 3.2): `bulk-seed` отработал, у товаров есть
   `saleor.binding(product.template)`. Без catalog-binding stock-sync товара даёт
   `CatalogBindingMissing` → arq retry → если каталога нет, уйдёт в failed.
2. Стек поднят (`docker compose ps` → db, odoo, redis, middleware, middleware-worker).
3. Модуль `saleor_sync` обновлён до v0.3 (включает stock automation):
   ```bash
   docker compose exec odoo odoo -d marketplace -u saleor_sync --stop-after-init
   docker compose restart odoo
   ```

## Первичная выгрузка остатков

```bash
docker compose exec middleware python -m saleor_bridge.cli.bulk_seed bulk-seed-stocks
```
Идемпотентно (`productVariantStocksUpdate` = upsert). Вывод — таблица
`Total / Synced / Skip / Failed`. `Skip` = варианты без catalog-binding (не из
каталога Saleor) — это норма. Exit 1 при `Failed > 0`.

## Инкрементальная синка (автоматом)

Меняешь остаток в Odoo (Inventory → Adjustments / валидация picking) → через ~5 сек
Saleor показывает `MAX(qty - buffer, 0)`. Проверка:

```graphql
query { productVariant(id:"<VARIANT_ID>"){ sku trackInventory quantityAvailable
  stocks{ quantity warehouse{ slug } } } }
```

## Safety buffer (ADR-0016)

`BRIDGE_STOCK_SAFETY_BUFFER` (env, дефолт 1). На витрину уходит `MAX(raw - buffer, 0)`.
Поэтому Saleor всегда на `buffer` меньше Odoo — это **ожидаемо**, не дрейф. Смена
buffer:
```bash
# .env → BRIDGE_STOCK_SAFETY_BUFFER=2, затем (НЕ restart — он не перечитывает env):
docker compose up -d middleware middleware-worker
docker compose exec middleware python -m saleor_bridge.cli.bulk_seed bulk-seed-stocks
```

## Troubleshooting

| Симптом | Причина | Действие |
|---------|---------|----------|
| Товар «нет в наличии» при ненулевом остатке | buffer съел остаток (raw ≤ buffer) или stock не засеян | `bulk-seed-stocks`; проверь `quantityAvailable` |
| Остаток не обновляется | automation не сработала / event не дошёл | `saleor.outbox` (Odoo) — есть запись? worker logs `stock_synced`? |
| `quantityAvailable=0` хотя `stocks.quantity>0` | warehouse не привязан к каналу | см. ADR-0015 (переиспользуй дефолтный warehouse), `reconcile-stocks` |
| Worker logs `CatalogBindingMissing` | каталог не синкнут для товара | `bulk-seed` (catalog) → потом `bulk-seed-stocks` |
| Дрейф Odoo vs Saleor | потерянный event | `reconcile-stocks` (см. [reconcile-procedure.md](reconcile-procedure.md)) |

## Известные ограничения (Phase 3.3)

- **Single warehouse** (ADR-0015): несколько складов Odoo схлопываются в один Saleor.
- **Reserved независим**: Odoo `reserved_quantity` (picking) и Saleor reservation
  (checkout) — две независимые системы. Phase 3.3 их НЕ синхронизирует. Stock-sync
  пушит только on-hand `quantity`; Saleor `quantityReserved` мы не трогаем.
- **trackInventory** переключается в `True` при первом stock-sync варианта (нужно
  для «нет в наличии» при 0). До этого (Phase 3.2) был `False`.
