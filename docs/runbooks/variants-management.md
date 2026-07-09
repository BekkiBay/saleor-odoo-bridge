# Runbook — Variants & Attributes Odoo ↔ Saleor (Phase 3.5)

Синхронизация атрибутов (цвет/размер/…) и вариантов из Odoo на витрину Saleor.
Источник истины — Odoo. См. ADR-0023..0027 (и ADR-0007/0012 как базу).

## Архитектура

```
Odoo product.attribute / .value  ──┐
   trigger(name, display_type / html_color)
                                   │
Odoo product.template (write)      │   ← attribute_line_ids change, list_price
   trigger(on_create_or_write)     │
                                   │
Odoo product.template.attribute.value (PTAV)
   trigger(price_extra) → emit product.template parent
                                   │
Odoo product.product (variant)     │
   trigger(default_code, barcode, active)
   + stock.quant(quantity) → product.product (Phase 3.3)
                                   ▼
POST {middleware}/api/odoo-events?secret=…   {odoo_model, odoo_id, action}
   │ validate secret → enqueue arq (defer ~3s, dedup model+id+5s bucket) → 200
   ▼
arq worker: sync_odoo_record_to_saleor →
   • product.attribute[.value] → sync_attribute_to_saleor
       ensure Attribute (DROPDOWN/PRODUCT) + values + assign VARIANT to "Generic" (hasVariants=true)
   • product.template → sync_product_to_saleor + sync_template_variants_to_saleor
       реконсиляция набора вариантов (create bulk / adopt / delete) + цены
   • product.product → sync_variant_to_saleor (ensure variant + price + attrs) → sync_stock_to_saleor
```

**Ключевое:**
- Одно событие `product.product` приходит от ДВУХ триггеров (variant-поля И
  `stock.quant`). Дедуп-бакет без `action`, поэтому handler делает оба: ensure
  варианта, затем остаток (ADR-0017). Идемпотентно → коллизия в бакете безопасна.
- `lst_price` на варианте — **non-stored compute**, триггером быть не может. Цены
  идут через `product.template` (list_price) и PTAV (`price_extra`), ADR-0026.

## Предусловия

1. Каталог засеян (Phase 3.2) и варианты мигрированы (`bulk-seed-variants`).
2. Стек поднят: `docker compose ps` → db, odoo, redis, middleware, middleware-worker.
3. Модуль `saleor_sync` обновлён до v0.5 (variant/attribute automations):
   ```bash
   docker compose exec odoo odoo -d marketplace -u saleor_sync --stop-after-init
   docker compose restart odoo
   ```

## Операции

### Initial migration (existing single-variant → variant bindings)

```bash
docker compose exec middleware python -m saleor_bridge.cli.bulk_seed bulk-seed-variants
```
Усыновляет dummy-варианты (Phase 3.2), создаёт `saleor.binding(product.product)`.
Идемпотентно — повторный прогон no-op. Ожидаемо: 30 templates → 30 variant bindings.

### Создать атрибут с значениями (S1)

В Odoo: Inventory → Configuration → Attributes → New. Имя «Color», Display Type
любой (синкается как DROPDOWN, ADR-0027), `Variants Creation Mode` = `Instantly`
или `Dynamically` (НЕ `Never` — `no_variant` скипается). Добавить значения
Red/Blue/Green → Save. Webhook → Saleor Attribute + 3 values + assign к "Generic".

Проверка:
```bash
# в Saleor должен появиться attribute "Color" с 3 values
docker compose exec middleware python -c "import asyncio; ..."  # или verify_bindings.py
```

### Добавить варианты существующему товару (S2)

В Odoo на `product.template`: вкладка Attributes & Variants → Add line → Color
[Red, Blue], Size [S, M, L] → Save. Odoo создаст 6 `product.product`. Webhook
(template + PTAV + product.product burst, схлопывается 5s-бакетом) →
реконсиляция: dummy удалён, 6 вариантов созданы (bulk) с attribute-assignments и
ценой `list_price`.

### Надбавка за вариант (price_extra, S3)

В Odoo: на PTAV (Attribute line → конкретное значение, напр. Size: L) поле
`Extra Price` = 50000 → Save. Webhook (PTAV trigger → template event) →
реконсиляция переустановит цену вариантов: Saleor variant «Size L» = list_price + 50000.

### Архивировать вариант (S4)

В Odoo: `product.product` → archive (active=False). Webhook → variant удаляется в
Saleor (`productVariantDelete`, идемпотентно). Остальные варианты работают.

## Подводные камни

- **Порядок создания в Saleor:** attribute → assign к ProductType → variant с
  значением. Атрибуты синкать ДО вариантов, иначе `AttributeBindingMissing` → arq
  retry (само сойдётся, но первый прогон может ретраить).
- **SKU вариантов:** Odoo по умолчанию НЕ генерит `default_code` для авто-вариантов.
  Задавайте SKU вручную, иначе fallback `odoo-<id>` (ADR-0024). SKU уникален глобально.
- **Stock после пересоздания варианта:** delete+create меняет Saleor variant ID →
  остаток на старом ID пропадает. Реконсиляция дёргает stock-sync для новых
  вариантов; при сомнении — `bulk-seed-stocks` (ADR-0025).
- **Burst webhook'ов:** 1 добавление attribute_line → N PTAV + M product.product
  событий. 5s-бакет дедупит по (model, id). Если видите >50 событий на одно
  изменение — проверьте, не зациклился ли skip-guard.
- **`no_variant` атрибуты** (состав/материал) — скипаются (Phase 4, ADR-0027).

## Verify

```bash
.venv/bin/python scripts/verify_bindings.py   # Products/Categories/Attributes/Variants
```
Секции Attributes и Variants: orphan Odoo / dead binding / orphan Saleor / counts.
