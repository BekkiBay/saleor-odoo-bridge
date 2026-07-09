"""Финальные проверки. Возвращает (all_passed, [(name, ok, detail), ...])."""

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


def run_checks(cfg: Config, odoo: odoorpc.ODOO, *, expected_modules: list[str],
               expected_root_cats: list[str], expected_total_cats: int,
               expected_products: int) -> list[CheckResult]:

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
        return c.currency_id.name == "UZS", f"currency={c.currency_id.name}"

    def company_country() -> tuple[bool, str]:
        c = odoo.env["res.company"].browse(odoo.env["res.company"].search([], limit=1)[0])
        return (c.country_id.code or "") == "UZ", f"country={c.country_id.code}"

    def user_tz() -> tuple[bool, str]:
        u = odoo.env["res.users"].browse(odoo.env.uid)
        return u.tz == "Asia/Tashkent", f"tz={u.tz}"

    def root_categories() -> tuple[bool, str]:
        Cat = odoo.env["product.category"]
        ids = Cat.search([("parent_id", "=", False), ("name", "in", expected_root_cats)])
        names = sorted(r["name"] for r in Cat.read(ids, ["name"]))
        return set(names) >= set(expected_root_cats), f"roots={names}"

    def child_categories() -> tuple[bool, str]:
        Cat = odoo.env["product.category"]
        root_ids = Cat.search([("parent_id", "=", False), ("name", "in", expected_root_cats)])
        child_ids = Cat.search([("parent_id", "in", root_ids)])
        expected_children = expected_total_cats - len(expected_root_cats)
        return len(child_ids) == expected_children, (
            f"children={len(child_ids)} (expected {expected_children})"
        )

    def product_count() -> tuple[bool, str]:
        Tmpl = odoo.env["product.template"]
        ids = Tmpl.search([("default_code", "like", "SKU-%")])
        return len(ids) == expected_products, f"products={len(ids)} (expected {expected_products})"

    def all_have_sku() -> tuple[bool, str]:
        Tmpl = odoo.env["product.template"]
        ids = Tmpl.search([("default_code", "like", "SKU-%")])
        recs = Tmpl.read(ids, ["default_code"])
        empty = [r["id"] for r in recs if not r["default_code"]]
        return not empty, f"missing_sku_ids={empty}"

    def all_have_real_category() -> tuple[bool, str]:
        Tmpl = odoo.env["product.template"]
        ids = Tmpl.search([("default_code", "like", "SKU-%")])
        recs = Tmpl.read(ids, ["default_code", "categ_id"])
        bad = [r["default_code"] for r in recs if not r["categ_id"] or r["categ_id"][0] == 1]
        return not bad, f"with_default_category={bad}"

    def sample_price() -> tuple[bool, str]:
        Tmpl = odoo.env["product.template"]
        ids = Tmpl.search([("default_code", "=", "SKU-001")])
        if not ids:
            return False, "SKU-001 не найден"
        rec = Tmpl.read(ids[0], ["list_price"])[0]
        ok = abs(rec["list_price"] - 450000) < 0.01
        return ok, f"SKU-001 list_price={rec['list_price']}"

    def uzs_symbol() -> tuple[bool, str]:
        Currency = odoo.env["res.currency"].with_context(active_test=False)
        ids = Currency.search([("name", "=", "UZS")])
        sym = Currency.read(ids[0], ["symbol"])[0]["symbol"]
        return sym == "сўм", f"UZS symbol={sym!r}"

    def custom_view_present() -> tuple[bool, str]:
        View = odoo.env["ir.ui.view"]
        from .views import VIEW_NAME  # local import to avoid cycle
        ids = View.search([("name", "=", VIEW_NAME), ("model", "=", "product.template")])
        return bool(ids), f"view '{VIEW_NAME}' ids={ids}"

    return [
        _check("Containers running (db + odoo)", containers),
        _check("Odoo responds at /web/database/manager", http_ok),
        _check(f"Database '{cfg.db_name}' exists", db_present),
        _check(f"{len(expected_modules)} modules installed", modules_installed),
        _check("Company currency = UZS", company_currency),
        _check("Company country = UZ", company_country),
        _check("Admin user timezone = Asia/Tashkent", user_tz),
        _check(f"{len(expected_root_cats)} root categories", root_categories),
        _check(f"{expected_total_cats - len(expected_root_cats)} child categories", child_categories),
        _check(f"{expected_products} products in product.template", product_count),
        _check("All products have non-empty default_code", all_have_sku),
        _check("All products have non-default categ_id", all_have_real_category),
        _check("Sample: SKU-001 list_price == 450000", sample_price),
        _check("UZS currency symbol = 'сўм' (not 'лв')", uzs_symbol),
        _check("Custom product list view installed", custom_view_present),
    ]


def print_table(results: list[CheckResult]) -> bool:
    GREEN, RED, RESET = "\033[32m", "\033[31m", "\033[0m"
    all_ok = all(ok for _, ok, _ in results)

    name_w = max(len(n) for n, _, _ in results) + 2
    print("\n" + "─" * (name_w + 50))
    print(f"{'Check':<{name_w}} Result   Detail")
    print("─" * (name_w + 50))
    for name, ok, detail in results:
        mark = f"{GREEN}[✓]{RESET}" if ok else f"{RED}[✗]{RESET}"
        status = f"{GREEN}OK{RESET}" if ok else f"{RED}FAIL{RESET}"
        print(f"{mark} {name:<{name_w - 4}} {status:<8} {detail}")
    print("─" * (name_w + 50))

    if all_ok:
        print(f"{GREEN}✅ All {len(results)} checks passed.{RESET}")
    else:
        failed = sum(1 for _, ok, _ in results if not ok)
        print(f"{RED}❌ {failed}/{len(results)} checks failed.{RESET}")
    return all_ok
