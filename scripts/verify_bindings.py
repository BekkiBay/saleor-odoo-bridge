#!/usr/bin/env python3
"""Проверка консистентности saleor.binding между Odoo и Saleor (Phase 3.2 hardening).

Сверяет три направления:
  1. orphan Odoo   — активный product.template / каталожная category БЕЗ binding.
  2. dead binding  — binding.saleor_id, которого НЕТ в Saleor.
  3. orphan Saleor — Saleor product/category, на который НЕТ binding.
Плюс сверка counts: Odoo == Saleor == bindings.

«Каталожные категории» = достижимые вверх по parent_id от категорий активных
товаров (та же логика, что в bulk_seed). Odoo-дефолты (Goods/Services/Expenses)
в синк не входят и здесь НЕ считаются orphan.

Запуск (host, нужен .venv с odoorpc+requests):
    .venv/bin/python scripts/verify_bindings.py

Exit: 0 — консистентно, 1 — расхождения.
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from lib.client import connect_odoorpc, load_config  # noqa: E402

SALEOR_GQL = "http://localhost:8000/graphql/"
SALEOR_ADMIN_EMAIL = "admin@example.com"
SALEOR_ADMIN_PASSWORD = "admin"

GREEN, RED, RESET = "\033[32m", "\033[31m", "\033[0m"

_PROD = "product.template"
_CAT = "product.category"
_ATTR = "product.attribute"
_VARIANT = "product.product"


def gql(query: str, token: str | None = None, variables: dict | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.post(SALEOR_GQL, headers=headers,
                      json={"query": query, "variables": variables or {}}, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("errors"):
        sys.exit(f"GraphQL errors: {data['errors']}")
    return data["data"]


def saleor_token() -> str:
    d = gql("mutation($e:String!,$p:String!){tokenCreate(email:$e,password:$p){token}}",
            variables={"e": SALEOR_ADMIN_EMAIL, "p": SALEOR_ADMIN_PASSWORD})
    tok = d["tokenCreate"]["token"]
    if not tok:
        sys.exit("Saleor tokenCreate failed")
    return tok


def saleor_all(token: str, root: str) -> set[str]:
    ids: set[str] = set()
    after = None
    while True:
        q = (f'query($a:String){{ {root}(first:100, after:$a){{ '
             f'edges{{ node{{ id }} }} pageInfo{{ hasNextPage endCursor }} }} }}')
        conn = gql(q, token, {"a": after})[root]
        ids.update(e["node"]["id"] for e in conn["edges"])
        if not conn["pageInfo"]["hasNextPage"]:
            break
        after = conn["pageInfo"]["endCursor"]
    return ids


def catalog_category_ids(odoo) -> set[int]:
    """Категории, достижимые вверх по parent_id от категорий активных товаров."""
    Prod = odoo.env[_PROD]
    Cat = odoo.env[_CAT]
    prod_ids = Prod.search([("active", "=", True), ("sale_ok", "=", True)])
    leaf_ids = {p["categ_id"][0] for p in Prod.read(prod_ids, ["categ_id"]) if p["categ_id"]}
    all_cats = {c["id"]: c for c in Cat.search_read([], ["parent_id"])}
    reachable: set[int] = set()
    for cid in leaf_ids:
        cur = cid
        depth = 0
        while cur and cur in all_cats and cur not in reachable and depth <= 10:
            reachable.add(cur)
            parent = all_cats[cur]["parent_id"]
            cur = parent[0] if parent else None
            depth += 1
    return reachable


def managed_attribute_ids(token: str) -> set[str]:
    """Saleor attribute ids, которыми управляем МЫ = variant-атрибуты "Generic"
    ProductType (ADR-0023). Исключает demo/прочие атрибуты Saleor."""
    q = ('query{ productTypes(first:100, filter:{search:"Generic"}){ edges{ node{ '
         'name variantAttributes{ id } } } } }')
    ids: set[str] = set()
    for edge in gql(q, token)["productTypes"]["edges"]:
        if edge["node"]["name"] == "Generic":
            ids.update(a["id"] for a in edge["node"]["variantAttributes"])
    return ids


def check_section(name: str, odoo, model: str, saleor_root: str, token: str,
                  odoo_ids: set[int], saleor_ids: set[str] | None = None) -> list[str]:
    print(f"\n  {name}:")
    Binding = odoo.env["saleor.binding"]
    bindings = Binding.search_read([("model_name", "=", model)], ["odoo_id", "saleor_id"])
    bound_odoo_ids = {b["odoo_id"] for b in bindings}
    binding_saleor_ids = {b["saleor_id"] for b in bindings if not str(b["saleor_id"]).startswith("<")}
    if saleor_ids is None:
        saleor_ids = saleor_all(token, saleor_root)

    print(f"  {'Odoo (catalog)':<28}: {len(odoo_ids)}")
    print(f"  {'Saleor':<28}: {len(saleor_ids)}")
    print(f"  {'Bindings ('+model+')':<28}: {len(bindings)}")

    problems: list[str] = []

    orphan_odoo = odoo_ids - bound_odoo_ids
    if orphan_odoo:
        problems.append(f"orphan Odoo {model}: ids={sorted(orphan_odoo)} → re-sync (bulk-seed/retry-failed)")
        print(f"  {RED}X orphan Odoo records: {sorted(orphan_odoo)}{RESET}")
    else:
        print(f"  {GREEN}OK No orphan Odoo records{RESET}")

    dead = binding_saleor_ids - saleor_ids
    if dead:
        problems.append(f"dead bindings ({model}): saleor_id={sorted(dead)} → delete binding + re-sync")
        print(f"  {RED}X dead bindings: {sorted(dead)}{RESET}")
    else:
        print(f"  {GREEN}OK No dead bindings{RESET}")

    orphan_saleor = saleor_ids - binding_saleor_ids
    if orphan_saleor:
        problems.append(f"orphan Saleor {saleor_root}: ids={sorted(orphan_saleor)} → wipe+seed or delete in Saleor")
        print(f"  {RED}X orphan Saleor records: {sorted(orphan_saleor)}{RESET}")
    else:
        print(f"  {GREEN}OK No orphan Saleor records{RESET}")

    if len(odoo_ids) == len(saleor_ids) == len(binding_saleor_ids):
        print(f"  {GREEN}OK Counts match{RESET}")
    else:
        problems.append(f"count mismatch ({model}): odoo={len(odoo_ids)} "
                        f"saleor={len(saleor_ids)} bindings={len(binding_saleor_ids)}")
        print(f"  {RED}X Counts mismatch{RESET}")

    return problems


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    cfg = load_config()
    odoo = connect_odoorpc(cfg, db=cfg.db_name)
    token = saleor_token()

    print("Binding integrity check:")
    problems: list[str] = []
    prod_ids = set(odoo.env[_PROD].search([("active", "=", True), ("sale_ok", "=", True)]))
    problems += check_section("Products", odoo, _PROD, "products", token, prod_ids)
    problems += check_section("Categories", odoo, _CAT, "categories", token, catalog_category_ids(odoo))

    # Phase 3.5: attributes (variant-defining) + variants (product.product).
    # Saleor-сторона скоупится на variant-атрибуты "Generic" типа (наши), чтобы
    # demo/прочие атрибуты Saleor не считались orphan (ADR-0023).
    attr_ids = set(odoo.env[_ATTR].search([("create_variant", "!=", "no_variant")]))
    problems += check_section("Attributes", odoo, _ATTR, "attributes", token, attr_ids,
                              saleor_ids=managed_attribute_ids(token))
    variant_ids = set(odoo.env[_VARIANT].search(
        [("active", "=", True), ("product_tmpl_id.sale_ok", "=", True)]
    ))
    problems += check_section("Variants", odoo, _VARIANT, "productVariants", token, variant_ids)

    print()
    if problems:
        print(f"{RED}FAIL — {len(problems)} issue(s):{RESET}")
        for p in problems:
            print(f"   - {p}")
        return 1
    print(f"{GREEN}All checks passed{RESET}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
