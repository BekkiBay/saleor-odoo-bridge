#!/usr/bin/env python3
"""Orchestrator: provision a local Odoo instance for the bridge.

Creates the database, installs the modules the bridge needs (including the
`saleor_sync` addon), configures the main company, and verifies the result.
It does not import any catalog — products come from your own Odoo data.

Run from the repository root (where docker-compose.yml lives):

    python scripts/odoo_setup.py --reset     # drop and recreate the database
    python scripts/odoo_setup.py             # idempotent run
    python scripts/odoo_setup.py --dry-run   # show the plan, change nothing

See scripts/README.md.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from lib import company as comp_mod  # noqa: E402
from lib import database as db_mod  # noqa: E402
from lib import modules as mod_mod  # noqa: E402
from lib import verify as verify_mod  # noqa: E402
from lib.client import Config, connect_odoorpc, load_config  # noqa: E402

PROJECT_ROOT = HERE.parent
# saleor_sync is the addon shipped in odoo/addons. Listing it last lets Odoo
# pull in its dependencies automatically.
EXPECTED_MODULES = ["contacts", "stock", "sale_management", "account", "saleor_sync"]


def step(n: int, title: str) -> None:
    print(f"\n\033[36m━━ Step {n}: {title} ━━\033[0m")


def info(msg: str) -> None:
    print(f"  {msg}")


def die(msg: str, code: int = 1) -> None:
    print(f"\n\033[31mFATAL: {msg}\033[0m", file=sys.stderr)
    sys.exit(code)


def ensure_containers_running() -> None:
    result = subprocess.run(
        ["docker", "compose", "ps", "--status", "running", "--format", "{{.Service}}"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT), check=False,
    )
    running = set(result.stdout.split())
    if {"db", "odoo"}.issubset(running):
        info("✓ docker compose: db + odoo already running")
        return
    info(f"docker compose ps → {sorted(running) or 'nothing running'}, running `up -d`")
    up = subprocess.run(
        ["docker", "compose", "up", "-d"],
        cwd=str(PROJECT_ROOT), check=False, capture_output=True, text=True,
    )
    if up.returncode != 0:
        die(f"docker compose up -d failed:\n{up.stderr}")
    info("✓ docker compose up -d succeeded")


def wait_for_odoo_http(url: str, timeout: int = 90) -> None:
    deadline = time.time() + timeout
    last_err = "?"
    while time.time() < deadline:
        try:
            r = requests.get(f"{url}/web/database/manager", timeout=5, allow_redirects=False)
            if r.status_code in (200, 303):
                info(f"✓ Odoo responds (HTTP {r.status_code})")
                return
            last_err = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            last_err = str(e)[:80]
        time.sleep(2)
    die(f"Odoo did not respond within {timeout}s (last: {last_err})")


def preflight(cfg: Config) -> None:
    step(1, "Pre-flight checks")
    ensure_containers_running()
    wait_for_odoo_http(cfg.url)


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision a local Odoo for the Saleor bridge")
    parser.add_argument("--reset", action="store_true",
                        help="drop the existing database and create it from scratch")
    parser.add_argument("--dry-run", action="store_true",
                        help="show the plan without changing anything")
    args = parser.parse_args()

    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        die(f".env not found: {env_path}. Copy .env.example to .env.")
    load_dotenv(env_path)
    cfg = load_config()

    if args.dry_run:
        print("\n\033[33mDRY-RUN — nothing will be changed\033[0m")
        print(f"  ODOO_URL          = {cfg.url}")
        print(f"  ODOO_DB_NAME      = {cfg.db_name}")
        print(f"  ODOO_ADMIN_LOGIN  = {cfg.admin_login}")
        print(f"  ODOO_COMPANY_NAME = {cfg.company_name}")
        print(f"  reset             = {args.reset}")
        print("\nPlanned steps:")
        print("  1. pre-flight (containers, http, .env)")
        print(f"  2. database: {'drop+create' if args.reset else 'create if missing'} {cfg.db_name}")
        print(f"  3. modules: install {EXPECTED_MODULES}")
        print(f"  4. company: name={cfg.company_name}, {cfg.currency_code}, "
              f"{cfg.country_code}, {cfg.timezone}")
        print("  5. verification")
        return 0

    preflight(cfg)

    step(2, f"Database setup ({cfg.db_name})")
    exists = db_mod.database_exists(cfg, cfg.db_name)
    if exists and args.reset:
        db_mod.drop_database(cfg, cfg.db_name)
        db_mod.create_database(cfg, cfg.db_name)
    elif exists:
        info(f"✓ database '{cfg.db_name}' already exists, no --reset → skipping creation")
    else:
        db_mod.create_database(cfg, cfg.db_name)

    step(3, "Module installation")
    odoo = connect_odoorpc(cfg, db=cfg.db_name)
    mod_mod.ensure_modules(odoo, EXPECTED_MODULES)

    step(4, "Company configuration")
    comp_mod.configure_company(
        odoo,
        name=cfg.company_name,
        currency_code=cfg.currency_code,
        country_code=cfg.country_code,
        timezone=cfg.timezone,
        lang=cfg.lang,
    )

    step(5, "Verification")
    results = verify_mod.run_checks(cfg, odoo, expected_modules=EXPECTED_MODULES)
    all_ok = verify_mod.print_table(results)

    if not all_ok:
        return 1

    print()
    print("\033[32m✅ Odoo is provisioned\033[0m")
    print(f"  Database: {cfg.db_name}")
    print(f"  URL:      {cfg.url}")
    print(f"  Login:    {cfg.admin_login}")
    print("  Password: (see ODOO_ADMIN_USER_PASSWORD in .env)")
    print()
    print("  Next:")
    print("    1. python scripts/generate_api_key.py   # Odoo API key for the middleware")
    print("    2. python scripts/install_bridge_app.py # register the app in Saleor")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n^C interrupted")
        sys.exit(130)
