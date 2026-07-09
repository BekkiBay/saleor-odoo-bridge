# Odoo setup

A local Docker Compose stack with **Odoo 19 Community** + PostgreSQL 16 — the
operational back office (source of truth for products, stock, orders, and
customers). Saleor is connected separately.

## Requirements

- Docker **24+**
- Docker Compose **v2** (`docker compose ...`)
- Python **3.10+** (for the automation scripts in `scripts/`)
- Free port **8069** on localhost
- ~2 GB of free RAM for the containers

## Quick start

```bash
# 1. Fill in the secrets in .env at the repo root (copy it from .env.example):
cp .env.example .env
docker compose up -d           # 2. Bring up the stack
open http://localhost:8069     # 3. Odoo UI
```

After that, either configure things manually through the UI (see below), or
run the automation:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt
python scripts/odoo_setup.py --reset       # creates the DB, installs modules, imports the catalog
```

See `scripts/README.md` for details.

## First run — creating the database through the UI (if you're not using the script)

On the `/web/database/manager` screen:

| Field            | Value (example)                             |
| ----------------- | -------------------------------------------- |
| Master Password  | `ODOO_ADMIN_PASSWORD` from `.env`             |
| Database Name    | `marketplace` — just an example, pick any name |
| Email             | your email (this becomes the admin login)     |
| Password          | a strong password for the admin user          |
| Language          | your choice, e.g. English                     |
| Country           | your choice, e.g. Uzbekistan (shown here only as an example) |
| Demo data         | **Leave unchecked** (important)               |

## Which modules to install (Apps)

- ✅ **Contacts** — customer directory
- ✅ **Inventory** — stock
- ✅ **Sales** — orders
- ✅ **Invoicing** — dependency of Sales

## Which modules NOT to install, and why

- ❌ **CRM** — B2B sales pipeline (leads/opportunities); not useful for a B2C
  marketplace. Covered by Contacts + dashboards instead.
- ❌ **Website**, **eCommerce** — the public storefront is Saleor.
- ❌ **Marketing Automation**, **Email Marketing** — add later, as a separate effort.
- ❌ **HR / Payroll / Employees** — not needed for this bridge.
- ❌ **l10n_ru**, **l10n_uz** — `l10n_ru` is a Russian chart of accounts and
  isn't needed here; there is no good-quality `l10n_uz` either. Handle
  accounting localization separately, for whichever country/region applies
  to your deployment.

## Company configuration

**Settings → Companies →** your company:

| Parameter | Example value                              |
| --------- | ------------------------------------------- |
| Currency  | e.g. UZS — use whatever currency you operate in |
| Country   | e.g. Uzbekistan — use your own country       |
| Timezone  | e.g. Asia/Tashkent — use your own timezone   |
| Language  | your choice, e.g. English                    |

## Everyday commands

```bash
docker compose up -d
docker compose stop                  # soft stop
docker compose down                  # remove containers (volumes are kept)
docker compose down -v               # ⚠️ wipes volumes (data loss)

docker compose logs -f odoo
docker compose logs -f db

./scripts/backup.sh                  # → ./backups/YYYY-MM-DD_HH-MM/
./scripts/backup.sh marketplace
./scripts/restore.sh ./backups/2026-05-20_14-30
./scripts/odoo-shell.sh              # default DB: marketplace
```

## Troubleshooting

**`bind: address already in use` on 8069** — run
`lsof -iTCP:8069 -sTCP:LISTEN`, kill the process, or change the port in
`docker-compose.yml`.

**Permission denied on volumes (Linux)** — `docker compose down -v && docker
compose up -d` (recreates the volumes correctly). Usually not an issue on
macOS.

**Slow first start** — Postgres is running `initdb`. Wait about 30 seconds.

**Forgot to set up `.env`** — copy `.env.example` to `.env` at the repo root,
fill in the values, then `docker compose up -d --force-recreate`.

**Changing `ODOO_ADMIN_PASSWORD`** — `docker compose up -d --force-recreate odoo`.
The database is unaffected.

**The currency shows the wrong symbol** — a few currencies ship with a legacy
symbol in stock Odoo (UZS, for instance, renders as `лв`). Add an entry to
`CURRENCY_SYMBOL_OVERRIDES` in `scripts/lib/company.py` and re-run
`odoo_setup.py`; it rewrites `res.currency.symbol` for that code.
