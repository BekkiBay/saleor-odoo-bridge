# scripts/ — автоматизация Odoo

Python-скрипты для настройки локального Odoo 19 через JSON-RPC + импорта каталога из xlsx. Управляются одним orchestrator'ом — `odoo_setup.py`.

## Требования

- Python **3.10+** (на macOS 3.9 тоже работает за счёт `from __future__ import annotations`)
- Запущенные `db` и `odoo` контейнеры (`docker compose up -d` в корне проекта — orchestrator поднимет их сам, если не запущены)
- `.env` с заполненными переменными (см. `.env.example` в корне)

## Установка

```bash
cd odoo-saleor-integration

python3 -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt
```

## Где взять xlsx

Файл `test-catalog-clothing-v2.xlsx` — приходит из чата (или от заказчика). Положи в `data/`:

```bash
mkdir -p data
cp ~/Downloads/test-catalog-clothing-v2.xlsx data/
```

Ожидаемые колонки (порядок не важен, имена точные):
`Артикул`, `Название`, `Категория товаров`, `Цена продажи (UZS)`, `Себестоимость (UZS)`, `Штрихкод`, `Описание`.

Категории — иерархия через ` / ` (например `Одежда / Платья`).

## Команды

```bash
# Полный сброс + настройка + импорт
python scripts/odoo_setup.py --reset

# Только настройка БД, без импорта
python scripts/odoo_setup.py --skip-import

# Идемпотентный прогон — ничего не сломает, добавит/обновит чего нет
python scripts/odoo_setup.py

# План без изменений
python scripts/odoo_setup.py --dry-run

# Другой xlsx
python scripts/odoo_setup.py --reset --catalog path/to/other.xlsx
```

## Что делает orchestrator

1. **Pre-flight** — поднимет docker compose если не запущен, дождётся HTTP Odoo, проверит .env + наличие xlsx.
2. **Database** — снесёт `marketplace` (если `--reset`) и создаст заново через `/web/database/create` с lang=ru_RU, country=uz, demo=false.
3. **Modules** — установит `contacts`, `stock`, `sale_management`, `account` через `ir.module.module.button_immediate_install`.
4. **Company** — `res.company` → currency UZS, country UZ, name из `.env`; пользователю admin выставит tz=Asia/Tashkent, lang=ru_RU.
5. **Categories** — создаст дерево `product.category` (идемпотентно, по `name + parent_id`).
6. **Products** — создаст/обновит `product.template` (идемпотентно, по `default_code`). Поддерживает Odoo 17+ (`is_storable`) и старее (`type='product'`) — автоматически определит.
7. **Verification** — 13 проверок (контейнеры, HTTP, БД, модули, валюта, страна, tz, категории, товары, SKU, ссылки на категории, цена SKU-001).
8. **Финальный отчёт** в stdout.

## Идемпотентность

| Сценарий                          | Поведение                                   |
| --------------------------------- | ------------------------------------------- |
| Свежая система, без флагов        | Всё создаст                                  |
| Повторный запуск без флагов       | Увидит существующее, ничего не сломает      |
| `--reset`                         | Снесёт БД и создаст с нуля                  |
| `--skip-import`                   | Импорт каталога не запускается              |

## Структура

```
scripts/
├── requirements.txt
├── odoo_setup.py              # orchestrator
├── lib/
│   ├── client.py              # Config, odoorpc, requests session
│   ├── database.py            # list/create/drop через /web/database/*
│   ├── modules.py             # ir.module.module
│   ├── company.py             # res.company + res.users
│   ├── categories.py          # product.category дерево
│   ├── products.py            # product.template + xlsx reader
│   └── verify.py              # финальные проверки + табличка
├── backup.sh / restore.sh / odoo-shell.sh
├── entrypoint.sh              # обёртка для docker для envsubst /etc/odoo/odoo.conf
└── README.md
```

## Troubleshooting

**`не удалось залогиниться в marketplace как admin@marketplace.local`** — проверь `ODOO_ADMIN_LOGIN` и `ODOO_ADMIN_USER_PASSWORD` в `.env`. Если БД создавалась с другими credentials — сделай `--reset`.

**`модули не найдены в ir.module.module: [...]`** — несовпадение technical_name в новой версии Odoo. Открой http://localhost:8069/odoo/apps, найди модуль, наведи курсор → в URL увидишь technical_name. Подставь в `lib/modules.py::REQUIRED_MODULES`.

**`storable field detected: type=product`** — версия Odoo старше 17. Должно работать.

**`docker compose up -d failed`** — запусти руками и посмотри stderr: `cd .. && docker compose up -d`. Чаще всего — порт 8069 занят или забыт `.env`.

**Запуск `--reset` падает на `create_database` с timeout** — создание БД на холодную = ~60–90с (initdb + base + ru_RU). Если упирается в 180с — проверь логи `docker compose logs odoo`.
