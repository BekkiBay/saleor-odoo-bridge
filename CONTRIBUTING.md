# Contributing

Thanks for considering a contribution. This bridge grew out of one production
deployment, so the most valuable contributions right now are the ones that make
it work for a second, third and fourth one.

## Getting set up

```bash
git clone https://github.com/BekkiBay/saleor-odoo-bridge
cd saleor-odoo-bridge
cp .env.example .env          # fill in the values

cd middleware
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                        # should be green before you change anything
```

The full stack (Postgres + Odoo + Redis + middleware + worker) comes up with
`docker compose up -d`. You bring your own Saleor instance; point
`BRIDGE_SALEOR_API_URL` at it.

## Before you open a pull request

```bash
cd middleware
ruff check .        # lint
mypy src            # type-check
pytest -q           # unit tests

cd ..
pytest -q odoo/addons/saleor_sync/tests/   # pure status-mapping tests, no Odoo needed
```

CI runs exactly these on Python 3.11 and 3.12, plus `docker compose config`.

## What we look for

**Tests.** Every behavioural change needs one. The suite is fast (under a
second) and fully mocked — there is no excuse to skip it. Sync logic lives in
`usecases/` and is tested with fake Odoo/Saleor clients; see
`tests/saleor_order_fakes.py` and `tests/stock_fakes.py`.

**Architecture.** The middleware is hexagonal:

- `adapters/saleor/` — Saleor payloads ↔ domain models
- `adapters/odoo/` — domain models ↔ Odoo JSON-RPC calls
- `domain/` — pure pydantic models, no Saleor or Odoo specifics
- `usecases/` — business logic, talks only to domain models and adapter ports

Keep platform specifics inside their adapter. If you find yourself importing a
Saleor type in `usecases/`, something belongs in a mapper instead.

**Decisions.** Non-obvious choices are recorded in `docs/adr/`. If you change
one, update its ADR or add a new one that supersedes it. If you make a new
non-obvious choice, write an ADR — it is a short file, and it is what keeps the
next contributor from silently undoing your reasoning.

## Known good first issues

- **Multi-warehouse.** `adapters/odoo/stock.py` picks the first
  `stock.warehouse` (ADR-0015). Most real deployments have several.
- **Multi-channel.** The bridge operates on one Saleor channel (ADR-0004).
- **Multiple product types.** Everything maps to one Saleor ProductType
  (ADR-0012).
- **Tighter typing.** `mypy src` passes, but `strict = true` does not yet.
  Tightening it module by module is a welcome PR.
- **Translations.** Odoo UI strings are English literals; wrapping them for
  i18n and shipping `.po` files would help non-English back-offices.

## Odoo addon changes

The addon lives in `odoo/addons/saleor_sync/`. Two rules:

1. **Renaming a stored field needs a migration.** Odoo silently creates a new
   empty column and orphans the old one, losing data. See
   `migrations/19.0.0.6.0/pre-migrate.py` for the pattern and
   `tests/test_migration_rename.py` for how to test one without a database, and
   bump `version` in `__manifest__.py` so the migration actually runs.
2. **Field names are a contract.** `data/base_automation_data.xml` references
   the auto-generated external id `saleor_sync.field_sale_order__<field>`, and
   the middleware reads fields by name over JSON-RPC. Rename in one commit,
   everywhere.

## Reporting bugs

Include your Saleor version, Odoo version, and the relevant middleware log
lines (`BRIDGE_LOG_LEVEL=DEBUG` gives structured JSON). If a sync failed, the
`saleor.binding` record in Odoo carries `sync_state` and `error_message` —
those two fields usually say what happened.

## License

By contributing you agree that your work is licensed under
[LGPL-3.0-or-later](LICENSE), the same license as the project.
