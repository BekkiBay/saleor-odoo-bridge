# odoo-saleor-integration

Локальный Docker Compose стенд с **Odoo 19 Community** + PostgreSQL 16 — операционный back-office для маркетплейса (источник истины по товарам, складу, заказам, клиентам). Saleor подключается отдельно.

## Требования

- Docker **24+**
- Docker Compose **v2** (`docker compose ...`)
- Python **3.10+** (для скриптов автоматизации в `scripts/`)
- Свободный порт **8069** на localhost
- ~2 GB свободного RAM под контейнеры

## Quick start

```bash
# 1. Заполни секреты в корневом /.env (см. ../.env.example) и прогон setup:
../scripts/setup-env.sh        # создаст симлинк odoo-saleor-integration/.env -> ../.env
docker compose up -d           # 2. Поднять стек
open http://localhost:8069     # 3. UI Odoo
```

После этого либо сделай ручную настройку через UI (см. ниже), либо запусти автоматизацию:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt
python scripts/odoo_setup.py --reset       # создаёт БД, ставит модули, импортирует каталог
```

Подробности в `scripts/README.md`.

## Первый запуск — создание БД через UI (если не используешь скрипт)

На экране `/web/database/manager`:

| Поле                | Значение                              |
| ------------------- | ------------------------------------- |
| Master Password     | `ODOO_ADMIN_PASSWORD` из `.env`       |
| Database Name       | `marketplace`                         |
| Email               | твой email (это будет логин admin)    |
| Password            | сильный пароль для пользователя admin |
| Language            | **Russian / Русский**                 |
| Country             | Uzbekistan                            |
| Demo data           | **Снять галочку** (важно)             |

## Какие модули установить (Apps)

- ✅ **Contacts** — справочник клиентов
- ✅ **Inventory** — склад
- ✅ **Sales** — заказы
- ✅ **Invoicing** — зависимость Sales

## Какие модули НЕ ставить и почему

- ❌ **CRM** — B2B sales pipeline (leads/opportunities), для B2C маркетплейса бесполезен. Закрывается Contacts + дашбордами.
- ❌ **Website**, **eCommerce** — публичная витрина = Saleor.
- ❌ **Marketing Automation**, **Email Marketing** — позже, отдельной фазой.
- ❌ **HR / Payroll / Employees** — не в Phase 0.
- ❌ **l10n_ru**, **l10n_uz** — l10n_ru это РФ-план счетов, не нужен. l10n_uz качественной нет. Бухгалтерскую локализацию решаем отдельно.

## Настройка компании

**Settings → Companies →** твоя компания:

| Параметр  | Значение            |
| --------- | ------------------- |
| Currency  | UZS                 |
| Country   | Uzbekistan          |
| Timezone  | Asia/Tashkent       |
| Language  | Русский             |

## Команды повседневной работы

```bash
docker compose up -d
docker compose stop                  # мягкая остановка
docker compose down                  # удалить контейнеры (volumes останутся)
docker compose down -v               # ⚠️ сносит volumes (потеря данных)

docker compose logs -f odoo
docker compose logs -f db

./scripts/backup.sh                  # → ./backups/YYYY-MM-DD_HH-MM/
./scripts/backup.sh marketplace
./scripts/restore.sh ./backups/2026-05-20_14-30
./scripts/odoo-shell.sh              # дефолт: marketplace
```

## Troubleshooting

**`bind: address already in use` на 8069** — `lsof -iTCP:8069 -sTCP:LISTEN`, прибей процесс или поменяй порт в `docker-compose.yml`.

**Permission denied на volumes (Linux)** — `docker compose down -v && docker compose up -d` (volume пересоздастся правильно). На macOS обычно не воспроизводится.

**Долгий первый старт** — postgres делает initdb. Подожди 30 секунд.

**Забыл `.env`** — заполни корневой `/.env` (см. `../.env.example`) и запусти `../scripts/setup-env.sh`.

**Меняешь `ODOO_ADMIN_PASSWORD`** — `docker compose up -d --force-recreate odoo`. БД не пострадает.

**`#REF!` / валюта UZS показывается как «лв»** — известное наследие шаблона Odoo. В скриптах автоматизации можно поправить `res.currency.symbol = 'сўм'` (см. `scripts/lib/company.py`).
