#!/usr/bin/env python3
"""Install the persistent Saleor App used by the bridge, with catalog permissions.

Needed for the Odoo→Saleor direction: the middleware calls Saleor mutations
(productCreate and friends) with this App's token. Saleor POSTs the token to
{public_url}/api/register → the middleware stores it in the Redis APL, where the
worker and the CLI read it from (see adapters/saleor/factory.py).

    python scripts/install_bridge_app.py            # install / reinstall
    python scripts/install_bridge_app.py --keep     # keep an existing app of the same name

Preconditions:
- The middleware is up and BRIDGE_MIDDLEWARE_PUBLIC_URL is reachable from Saleor
  (so it can fetch /api/manifest and call /api/register).
- Your Saleor instance is reachable, and you have staff credentials for it.

Configuration (all optional, via environment):
    SALEOR_GQL_URL, BRIDGE_MIDDLEWARE_PUBLIC_URL, BRIDGE_APP_NAME,
    SALEOR_ADMIN_EMAIL, SALEOR_ADMIN_PASSWORD
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

SALEOR_GQL = os.environ.get("SALEOR_GQL_URL", "http://localhost:8000/graphql/")
_PUBLIC_URL = os.environ.get("BRIDGE_MIDDLEWARE_PUBLIC_URL", "http://host.docker.internal:8080")
MANIFEST_URL = f"{_PUBLIC_URL.rstrip('/')}/api/manifest"
APP_NAME = os.environ.get("BRIDGE_APP_NAME", "Saleor Odoo Sync")
PERMISSIONS = [
    "MANAGE_PRODUCTS",
    "MANAGE_PRODUCT_TYPES_AND_ATTRIBUTES",
    "MANAGE_CHANNELS",
    "MANAGE_ORDERS",
    "MANAGE_USERS",
]
ADMIN_EMAIL = os.environ.get("SALEOR_ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.environ.get("SALEOR_ADMIN_PASSWORD", "admin")


def gql(query: str, token: str | None = None, variables: dict | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.post(SALEOR_GQL, headers=headers,
                      json={"query": query, "variables": variables or {}}, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("errors"):
        sys.exit(f"GraphQL errors: {json.dumps(data['errors'], ensure_ascii=False)}")
    return data["data"]


def admin_token() -> str:
    d = gql(
        "mutation($e:String!,$p:String!){ tokenCreate(email:$e,password:$p){ token errors{ message } } }",
        variables={"e": ADMIN_EMAIL, "p": ADMIN_PASSWORD},
    )
    tok = d["tokenCreate"]["token"]
    if not tok:
        sys.exit("tokenCreate не вернул token — проверь admin creds")
    return tok


def delete_existing(token: str) -> None:
    apps = gql("{ apps(first:100){ edges{ node{ id name } } } }", token)["apps"]["edges"]
    for e in apps:
        if e["node"]["name"] == APP_NAME:
            gql("mutation($id:ID!){ appDelete(id:$id){ errors{ message } } }", token, {"id": e["node"]["id"]})
            print(f"  removed existing app {e['node']['id']}")


def install(token: str) -> None:
    m = """mutation($name:String!,$url:String!,$perms:[PermissionEnum!]){
        appInstall(input:{appName:$name, manifestUrl:$url, activateAfterInstallation:true,
            permissions:$perms}){
            appInstallation{ id status } errors{ field message code permissions } } }"""
    res = gql(m, token, {"name": APP_NAME, "url": MANIFEST_URL, "perms": PERMISSIONS})["appInstall"]
    if res.get("errors"):
        sys.exit(f"appInstall errors: {res['errors']}")
    inst_id = res["appInstallation"]["id"]
    print(f"  appInstall started id={inst_id}")
    for _ in range(30):
        time.sleep(1)
        rows = gql("{ appsInstallations{ id status message } }", token)["appsInstallations"]
        ours = [r for r in rows if r["id"] == inst_id]
        if not ours:
            print("  ✓ installed (gone from appsInstallations)")
            return
        if ours[0]["status"] in ("INSTALLED", "SUCCESS"):
            print(f"  ✓ status={ours[0]['status']}")
            return
        if ours[0]["status"] == "FAILED":
            sys.exit(f"appInstall FAILED: {ours[0].get('message')}")
    sys.exit("appInstall не дошёл до SUCCESS за 30с")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="не удалять прежний одноимённый App")
    args = ap.parse_args()
    token = admin_token()
    if not args.keep:
        delete_existing(token)
    install(token)
    print(f"\n✅ App «{APP_NAME}» установлен с правами: {', '.join(PERMISSIONS)}")
    print("   Токен ушёл на /api/register → Redis APL. Проверь:")
    print("   docker compose exec redis redis-cli KEYS 'saleor_bridge:apl:*'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
