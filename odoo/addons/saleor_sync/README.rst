============
Saleor Sync
============

Odoo-side helper для двусторонней синхронизации с Saleor.

**Phase 3.0 — skeleton.** Содержит только:

- модель ``saleor.binding`` (external ID mapping таблица),
- ACL + tree/form views,
- меню ``Saleor Sync → Bindings``.

Реальная бизнес-логика (mappers, server actions, queue_job hooks) — в Phase 3.1+.

Зависимости
===========

- ``sale_management``
- ``stock``
- ``account``

**Опционально (Phase 3.1+):** ``queue_job`` из `OCA/queue <https://github.com/OCA/queue>`_.

Установка
=========

Через UI:

1. Apps → Update Apps List.
2. Поиск "Saleor Sync".
3. Install.

Или CLI:

.. code-block:: bash

   docker compose exec odoo odoo -d marketplace -i saleor_sync --stop-after-init

Конфигурация
============

В Phase 3.0 — конфигурации нет. Модуль просто разворачивает таблицу
``saleor.binding`` и UI к ней.

Установка OCA queue_job (Phase 3.1+)
=====================================

Когда понадобится background queue, добавь OCA queue в ``odoo/addons/``:

.. code-block:: bash

   cd odoo/addons
   git clone --depth 1 --branch 19.0 https://github.com/OCA/queue.git oca-queue
   # symlink или volume mount: oca-queue/queue_job нужен в addons_path

   docker compose restart odoo
   # Apps → Update Apps List → install queue_job

После установки ``queue_job`` — добавь его в ``saleor_sync/__manifest__.py``
в ``depends`` и сделай ``-u saleor_sync``.

См. также
=========

- `Phase 3 research doc <../../../docs/phase-3-integration-research.md>`_
- `ADR-0003: Odoo custom module <../../../docs/adr/0003-odoo-custom-module.md>`_
- `ADR-0007: SKU as natural key <../../../docs/adr/0007-sku-as-natural-key.md>`_
