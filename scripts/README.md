# scripts/ — Odoo and Saleor provisioning

Python scripts that stand up the Odoo side of the bridge and register the App in
Saleor. Run them from the repository root, with `.env` filled in.

## Requirements

- Python **3.10+**
- The `db` and `odoo` containers running (`docker compose up -d` — `odoo_setup.py`
  will start them itself if they are not)
- A populated `.env` (see `.env.example` at the repository root)

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt
```

## The usual order

```bash
python scripts/odoo_setup.py --reset       # 1. database, modules, company, checks
python scripts/generate_api_key.py         # 2. Odoo API key → BRIDGE_ODOO_API_KEY in .env
python scripts/install_bridge_app.py       # 3. register the App in your Saleor
python scripts/smoke_test.py               # 4. end-to-end: Saleor → middleware → Odoo
```

## What each script does

| Script | Purpose |
|---|---|
| `odoo_setup.py` | Orchestrator: creates the database, installs `saleor_sync` and its dependencies, configures the main company (name/currency/country/timezone from `.env`), then verifies the result. Does **not** import a catalog — your products come from your own Odoo data. |
| `generate_api_key.py` | Generates an Odoo API key (scope=NULL, 3-month TTL) for the middleware and rewrites `BRIDGE_ODOO_API_KEY` in `.env`. A reproducible replacement for driving `odoo shell` by hand. |
| `install_bridge_app.py` | Installs the persistent Saleor App so the middleware can call Saleor mutations. Idempotent: removes an existing app of the same name unless `--keep`. |
| `smoke_test.py` | End-to-end check: creates a customer in Saleor, waits for it to land in Odoo. |
| `verify_bindings.py` | Consistency checker for `saleor.binding`: orphans, dead references, count mismatches across products/categories/attributes/variants. |
| `verify_smoke.py` | Assertion helpers used by `smoke_test.py`. |
| `backup.sh` / `restore.sh` | `pg_dump` + filestore tarball, and the reverse. The database name defaults to `$ODOO_DB_NAME`. |
| `odoo-shell.sh` | Interactive `odoo shell` in the running container. |
| `entrypoint.sh` | Docker entrypoint: substitutes env vars into `odoo.conf`. |

## `odoo_setup.py` flags

```bash
python scripts/odoo_setup.py             # idempotent: create the DB only if missing
python scripts/odoo_setup.py --reset     # drop and recreate the database
python scripts/odoo_setup.py --dry-run   # print the plan, change nothing
```

## Configuration

Everything is read from the root `.env`. The locale-shaped settings are:

```
ODOO_COMPANY_NAME=My Company
ODOO_CURRENCY=USD
ODOO_COUNTRY=US
ODOO_TIMEZONE=UTC
ODOO_LANG=en_US
```

The Saleor-facing scripts additionally read `SALEOR_GQL_URL`, `SALEOR_ADMIN_EMAIL`
and `SALEOR_ADMIN_PASSWORD` (staff credentials, used only to register the App), plus
`BRIDGE_APP_NAME` for the app's display name.

## Troubleshooting

**`odoo_setup.py` fails at "Module installation"**
The `saleor_sync` addon must be visible to Odoo. The compose file mounts
`./odoo/addons` into the container; check it is there with
`docker compose exec odoo ls /mnt/extra-addons`.

**`generate_api_key.py` prints no key**
It runs inside `odoo shell` against `$ODOO_DB_NAME`. Confirm the database exists and
that `ODOO_ADMIN_LOGIN` matches a real user in it.

**`install_bridge_app.py` cannot reach the manifest**
Saleor fetches `BRIDGE_MIDDLEWARE_PUBLIC_URL/api/manifest` itself. From a Saleor
running in Docker, `localhost` is that container — use `host.docker.internal` or a
tunnel URL.
