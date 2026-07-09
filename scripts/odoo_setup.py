#!/usr/bin/env python3
"""Orchestrator: автоматическая настройка локального Odoo 19 + импорт каталога.

Запуск из корня проекта (где лежит docker-compose.yml):

    python scripts/odoo_setup.py --reset                 # снести и пересоздать
    python scripts/odoo_setup.py --skip-import           # только настройка БД
    python scripts/odoo_setup.py                         # идемпотентный прогон
    python scripts/odoo_setup.py --dry-run               # план без изменений

См. scripts/README.md.
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

from lib import categories as cat_mod  # noqa: E402
from lib import company as comp_mod  # noqa: E402
from lib import database as db_mod  # noqa: E402
from lib import modules as mod_mod  # noqa: E402
from lib import products as prod_mod  # noqa: E402
from lib import verify as verify_mod  # noqa: E402
from lib import views as views_mod  # noqa: E402
from lib.client import Config, connect_odoorpc, load_config  # noqa: E402


PROJECT_ROOT = HERE.parent
# saleor_sync — кастомный аддон из odoo/addons (depends: sale_management/stock/
# account). Ставится последним, deps подтянутся автоматически. queue_job НЕ
# нужен: middleware гоняет свой arq-воркер, модуль его не импортит (Phase 3.1).
EXPECTED_MODULES = ["contacts", "stock", "sale_management", "account", "saleor_sync"]
EXPECTED_ROOT_CATS = ["Одежда", "Обувь", "Аксессуары"]
EXPECTED_TOTAL_CATS = 18
EXPECTED_PRODUCTS = 30


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
        info("✓ docker compose: db + odoo уже запущены")
        return
    info(f"docker compose ps → {sorted(running) or 'ничего не запущено'}, делаю `up -d`")
    up = subprocess.run(
        ["docker", "compose", "up", "-d"],
        cwd=str(PROJECT_ROOT), check=False, capture_output=True, text=True,
    )
    if up.returncode != 0:
        die(f"docker compose up -d failed:\n{up.stderr}")
    info("✓ docker compose up -d отработал")


def wait_for_odoo_http(url: str, timeout: int = 90) -> None:
    deadline = time.time() + timeout
    last_err = "?"
    while time.time() < deadline:
        try:
            r = requests.get(f"{url}/web/database/manager", timeout=5, allow_redirects=False)
            if r.status_code in (200, 303):
                info(f"✓ Odoo отвечает (HTTP {r.status_code})")
                return
            last_err = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            last_err = str(e)[:80]
        time.sleep(2)
    die(f"Odoo не ответил за {timeout}с (last: {last_err})")


def preflight(cfg: Config, catalog_path: Path, skip_import: bool) -> None:
    step(1, "Pre-flight checks")
    ensure_containers_running()
    wait_for_odoo_http(cfg.url)
    if not skip_import:
        if not catalog_path.exists():
            die(f"файл каталога не найден: {catalog_path}")
        info(f"✓ каталог найден: {catalog_path} ({catalog_path.stat().st_size} bytes)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Odoo Phase 1 — auto setup & catalog import")
    parser.add_argument("--reset", action="store_true",
                        help="снести существующую БД и создать заново")
    parser.add_argument("--skip-import", action="store_true",
                        help="пропустить импорт каталога (только настройка)")
    parser.add_argument("--catalog", default="data/test-catalog-clothing-v2.xlsx",
                        help="путь к xlsx с каталогом")
    parser.add_argument("--dry-run", action="store_true",
                        help="показать план без изменений")
    args = parser.parse_args()

    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        die(f".env не найден: {env_path}. Скопируй .env.example в .env.")
    load_dotenv(env_path)
    cfg = load_config()

    catalog_path = (PROJECT_ROOT / args.catalog).resolve() if not Path(args.catalog).is_absolute() else Path(args.catalog)

    if args.dry_run:
        print("\n\033[33mDRY-RUN — изменений делаться не будет\033[0m")
        print(f"  ODOO_URL          = {cfg.url}")
        print(f"  ODOO_DB_NAME      = {cfg.db_name}")
        print(f"  ODOO_ADMIN_LOGIN  = {cfg.admin_login}")
        print(f"  ODOO_COMPANY_NAME = {cfg.company_name}")
        print(f"  catalog           = {catalog_path}")
        print(f"  reset             = {args.reset}")
        print(f"  skip_import       = {args.skip_import}")
        print("\nПлан шагов:")
        print("  1. pre-flight (контейнеры, http, .env, файл)")
        print(f"  2. database: {'drop+create' if args.reset else 'create если нет'} {cfg.db_name}")
        print(f"  3. modules: install {EXPECTED_MODULES}")
        print(f"  4. company: name={cfg.company_name}, UZS, UZ, Asia/Tashkent")
        if not args.skip_import:
            print(f"  5. categories: дерево из {catalog_path.name}")
            print(f"  6. products: ~{EXPECTED_PRODUCTS} штук")
        print("  7. verification (13 чеков)")
        return 0

    preflight(cfg, catalog_path, args.skip_import)

    step(2, f"Database setup ({cfg.db_name})")
    exists = db_mod.database_exists(cfg, cfg.db_name)
    if exists and args.reset:
        db_mod.drop_database(cfg, cfg.db_name)
        db_mod.create_database(cfg, cfg.db_name)
    elif exists:
        info(f"✓ БД '{cfg.db_name}' уже существует, --reset не указан → пропускаю создание")
    else:
        db_mod.create_database(cfg, cfg.db_name)

    step(3, "Module installation")
    odoo = connect_odoorpc(cfg, db=cfg.db_name)
    mod_mod.ensure_modules(odoo, EXPECTED_MODULES)

    step(4, "Company configuration")
    comp_mod.configure_company(odoo, name=cfg.company_name)

    step(5, "UI customizations")
    views_mod.ensure_category_in_product_list(odoo)

    if not args.skip_import:
        step(6, "Categories import")
        rows = prod_mod.read_catalog(catalog_path)
        info(f"прочитано {len(rows)} строк из xlsx")
        mapping = cat_mod.build_category_tree(odoo, [r.category_path for r in rows])
        info(f"всего категорий замаплено: {len(mapping)}")

        step(7, "Products import")
        prod_mod.import_products(odoo, rows, mapping)
    else:
        info("⊘ skip-import: каталог не импортируется")

    step(8, "Verification")
    results = verify_mod.run_checks(
        cfg, odoo,
        expected_modules=EXPECTED_MODULES,
        expected_root_cats=EXPECTED_ROOT_CATS,
        expected_total_cats=EXPECTED_TOTAL_CATS,
        expected_products=0 if args.skip_import else EXPECTED_PRODUCTS,
    )
    if args.skip_import:
        results = [r for r in results if "categor" not in r[0].lower() and "product" not in r[0].lower() and "SKU" not in r[0]]
    all_ok = verify_mod.print_table(results)

    if all_ok:
        print()
        print("\033[32m✅ Phase 1-local complete\033[0m")
        print(f"  Database: {cfg.db_name}")
        print(f"  URL:      {cfg.url}")
        print(f"  Login:    {cfg.admin_login}")
        print(f"  Password: (см. ODOO_ADMIN_USER_PASSWORD в .env)")
        print()
        print("  Stats:")
        print(f"    Modules installed: {len(EXPECTED_MODULES)}")
        if not args.skip_import:
            print(f"    Categories created: {EXPECTED_TOTAL_CATS} ({len(EXPECTED_ROOT_CATS)} root + {EXPECTED_TOTAL_CATS - len(EXPECTED_ROOT_CATS)} nested)")
            print(f"    Products imported: {EXPECTED_PRODUCTS}")
        print(f"    Currency: UZS")
        print(f"    Timezone: Asia/Tashkent")
        print()
        print("  Next: open http://localhost:8069, log in, navigate to Inventory → Products")
        return 0
    else:
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n^C interrupted")
        sys.exit(130)
