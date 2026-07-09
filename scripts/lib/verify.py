"""Post-setup checks. Returns [(name, ok, detail), ...]."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

import odoorpc
import requests

from .client import Config

CheckResult = tuple[str, bool, str]


def _check(name: str, fn: Callable[[], tuple[bool, str]]) -> CheckResult:
    try:
        ok, detail = fn()
    except Exception as e:  # noqa: BLE001
        return name, False, f"exception: {e}"
    return name, ok, detail


def _compose_dir() -> str:
    here = Path(__file__).resolve()
    return str(here.parent.parent.parent)


def run_checks(cfg: Config, odoo: odoorpc.ODOO, *, expected_modules: list[str]) -> list[CheckResult]:
    """Verify that the Odoo side of the bridge is installed and configured."""

    def containers() -> tuple[bool, str]:
        out = subprocess.run(
            ["docker", "compose", "ps", "--status", "running", "--format", "{{.Service}}"],
            capture_output=True, text=True, cwd=_compose_dir(), check=False,
        )
        services = set(out.stdout.split())
        ok = {"db", "odoo"}.issubset(services)
        return ok, f"running: {sorted(services)}"

    def http_ok() -> tuple[bool, str]:
        r = requests.get(f"{cfg.url}/web/database/manager", timeout=10, allow_redirects=False)
        return r.status_code in (200, 303), f"HTTP {r.status_code}"

    def db_present() -> tuple[bool, str]:
        odoo_anon = odoorpc.ODOO(cfg.host, protocol=cfg.protocol, port=cfg.port)
        dbs = list(odoo_anon.db.list())
        return cfg.db_name in dbs, f"databases={dbs}"

    def modules_installed() -> tuple[bool, str]:
        Mod = odoo.env["ir.module.module"]
        ids = Mod.search([("name", "in", expected_modules), ("state", "=", "installed")])
        installed = [r["name"] for r in Mod.read(ids, ["name"])]
        ok = set(installed) == set(expected_modules)
        return ok, f"installed={sorted(installed)}"

    def company_currency() -> tuple[bool, str]:
        c = odoo.env["res.company"].browse(odoo.env["res.company"].search([], limit=1)[0])
        name = c.currency_id.name
        return name == cfg.currency_code, f"currency={name} (expected {cfg.currency_code})"

    def company_country() -> tuple[bool, str]:
        c = odoo.env["res.company"].browse(odoo.env["res.company"].search([], limit=1)[0])
        code = c.country_id.code or ""
        return code == cfg.country_code, f"country={code} (expected {cfg.country_code})"

    def user_tz() -> tuple[bool, str]:
        u = odoo.env["res.users"].browse(odoo.env.uid)
        return u.tz == cfg.timezone, f"tz={u.tz} (expected {cfg.timezone})"

    def bridge_models_present() -> tuple[bool, str]:
        """saleor_sync installs these; without them nothing can sync."""
        Model = odoo.env["ir.model"]
        wanted = {"saleor.binding", "saleor.outbox"}
        ids = Model.search([("model", "in", list(wanted))])
        found = {r["model"] for r in Model.read(ids, ["model"])}
        return found == wanted, f"models={sorted(found)}"

    def fulfillment_field_present() -> tuple[bool, str]:
        """The renamed status field the middleware reads back over JSON-RPC."""
        Field = odoo.env["ir.model.fields"]
        ids = Field.search([
            ("model", "=", "sale.order"),
            ("name", "in", ["fulfillment_status", "delivered_to_customer"]),
        ])
        names = sorted(r["name"] for r in Field.read(ids, ["name"]))
        return len(names) == 2, f"fields={names}"

    return [
        _check("Containers running (db + odoo)", containers),
        _check("Odoo responds at /web/database/manager", http_ok),
        _check(f"Database '{cfg.db_name}' exists", db_present),
        _check(f"{len(expected_modules)} modules installed", modules_installed),
        _check(f"Company currency = {cfg.currency_code}", company_currency),
        _check(f"Company country = {cfg.country_code}", company_country),
        _check(f"Admin user timezone = {cfg.timezone}", user_tz),
        _check("saleor.binding + saleor.outbox models exist", bridge_models_present),
        _check("sale.order has fulfillment_status + delivered_to_customer", fulfillment_field_present),
    ]


def print_table(results: list[CheckResult]) -> bool:
    """Print the check table; return True when everything passed."""
    width = max(len(name) for name, _, _ in results) + 2
    all_ok = True
    for name, ok, detail in results:
        mark = "\033[32m✓\033[0m" if ok else "\033[31m✗\033[0m"
        all_ok = all_ok and ok
        print(f"  {mark} {name.ljust(width)} {detail}")
    return all_ok
