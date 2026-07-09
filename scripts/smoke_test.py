#!/usr/bin/env python3
"""Smoke test Phase 3.0+3.1: Saleor → Middleware → Odoo end-to-end (local, без ngrok).

Гоняет НАСТОЯЩИЙ flow: Saleor подписывает webhook (JWS) → middleware верифицирует
→ enqueue в arq → worker пишет в Odoo. Никакого прямого enqueue.

    python scripts/smoke_test.py                 # полный прогон, exit 0 = OK
    python scripts/smoke_test.py --keep-app      # не удалять Saleor App в конце

Предусловия (см. docs/runbooks/smoke-test.md):
- docker compose up: odoo, db, redis, middleware, middleware-worker
- Saleor стек запущен (saleor-api-1 на :8000)
- odoo_setup.py --reset выполнен (saleor_sync installed)
- generate_api_key.py выполнен (BRIDGE_ODOO_API_KEY в .env)
- BRIDGE_MIDDLEWARE_PUBLIC_URL=http://host.docker.internal:8080, middleware up -d
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from dotenv import load_dotenv  # noqa: E402

from lib.client import connect_odoorpc, load_config  # noqa: E402
from verify_smoke import verify  # noqa: E402

# ── config ──────────────────────────────────────────────────────────────────
SALEOR_GQL = "http://localhost:8000/graphql/"
MIDDLEWARE = "http://localhost:8080"
MANIFEST_URL = "http://host.docker.internal:8080/api/manifest"
APP_NAME = "Justix Odoo Sync (Smoke)"
PERMISSIONS = [
    "MANAGE_ORDERS", "MANAGE_PRODUCTS", "MANAGE_USERS",
    "MANAGE_PRODUCT_TYPES_AND_ATTRIBUTES", "MANAGE_CHANNELS",
]
SALEOR_ADMIN_EMAIL = "admin@example.com"
SALEOR_ADMIN_PASSWORD = "admin"

GREEN, RED, CYAN, RESET = "\033[32m", "\033[31m", "\033[36m", "\033[0m"


def step(msg: str) -> None:
    print(f"\n{CYAN}━━ {msg} ━━{RESET}")


def ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET} {msg}")


def fail(msg: str) -> None:
    print(f"\n{RED}FAIL: {msg}{RESET}", file=sys.stderr)
    sys.exit(1)


def gql(query: str, token: str | None = None, variables: dict | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.post(
        SALEOR_GQL, headers=headers,
        json={"query": query, "variables": variables or {}}, timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("errors"):
        fail(f"GraphQL errors: {json.dumps(data['errors'], ensure_ascii=False)}")
    return data["data"]


def dc(*args: str) -> str:
    """docker compose ... → stdout."""
    r = subprocess.run(
        ["docker", "compose", *args],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True, check=False,
    )
    return r.stdout + r.stderr


# ── steps ───────────────────────────────────────────────────────────────────

def check_health() -> None:
    step("Pre-flight: middleware health")
    r = requests.get(f"{MIDDLEWARE}/health", timeout=5)
    body = r.json()
    if body.get("status") != "ok":
        fail(f"middleware /health не ok: {body}")
    ok(f"/health = {body}")


def get_admin_token() -> str:
    step("Saleor admin token (tokenCreate)")
    q = """mutation($e:String!,$p:String!){ tokenCreate(email:$e,password:$p){
        token errors{ field message code } } }"""
    d = gql(q, variables={"e": SALEOR_ADMIN_EMAIL, "p": SALEOR_ADMIN_PASSWORD})
    res = d["tokenCreate"]
    if res.get("errors"):
        fail(
            f"tokenCreate errors: {res['errors']}\n"
            f"  Проверь Saleor admin creds (default admin@example.com/admin).\n"
            f"  Передай вручную если другие — правь SALEOR_ADMIN_* в smoke_test.py."
        )
    if not res.get("token"):
        fail("tokenCreate не вернул token")
    ok(f"token получен ({SALEOR_ADMIN_EMAIL})")
    return res["token"]


def delete_existing_apps(token: str) -> None:
    step("Cleanup: удалить прежние smoke App'ы")
    q = """{ apps(first:50){ edges{ node{ id name } } } }"""
    apps = gql(q, token)["apps"]["edges"]
    targets = [e["node"] for e in apps if e["node"]["name"] == APP_NAME]
    if not targets:
        ok("прежних App с таким именем нет")
        return
    for app in targets:
        m = """mutation($id:ID!){ appDelete(id:$id){ app{id} errors{message} } }"""
        gql(m, token, {"id": app["id"]})
        ok(f"удалён прежний App {app['id']}")


def install_app(token: str) -> None:
    step("appInstall (manifest + permissions)")
    m = """mutation($name:String!,$url:String!,$perms:[PermissionEnum!]){
        appInstall(input:{appName:$name, manifestUrl:$url, activateAfterInstallation:true,
            permissions:$perms}){
            appInstallation{ id status appName manifestUrl }
            errors{ field message code permissions } } }"""
    d = gql(m, token, {"name": APP_NAME, "url": MANIFEST_URL, "perms": PERMISSIONS})
    res = d["appInstall"]
    if res.get("errors"):
        fail(f"appInstall errors: {res['errors']}")
    inst = res["appInstallation"]
    ok(f"appInstall запущен: id={inst['id']} status={inst['status']}")

    # poll installation status
    q = """{ appsInstallations{ id status appName message } }"""
    for _ in range(30):
        time.sleep(1)
        rows = gql(q, token)["appsInstallations"]
        ours = [r for r in rows if r["id"] == inst["id"]]
        if not ours:
            # пропал из installations → значит установился (перешёл в apps)
            ok("installation завершён (исчез из appsInstallations → INSTALLED)")
            return
        st = ours[0]["status"]
        if st in ("INSTALLED", "SUCCESS"):  # JobStatusEnum.SUCCESS
            ok(f"status={st}")
            return
        if st == "FAILED":
            fail(f"appInstall FAILED: {ours[0].get('message')}")
    fail("appInstall не дошёл до SUCCESS за 30с")


def verify_app(token: str) -> dict:
    step("Verify App + webhooks в Saleor")
    q = """{ apps(first:50){ edges{ node{ id name isActive
        webhooks{ id name isActive targetUrl asyncEvents{ eventType } } } } } }"""
    apps = gql(q, token)["apps"]["edges"]
    ours = [e["node"] for e in apps if e["node"]["name"] == APP_NAME]
    if not ours:
        fail(f"App {APP_NAME!r} не найден после установки")
    app = ours[-1]
    if not app["isActive"]:
        fail("App не active")
    active_wh = [w for w in app["webhooks"] if w["isActive"]]
    ok(f"App active, webhooks: {len(active_wh)} active / {len(app['webhooks'])} total")
    for w in app["webhooks"]:
        evs = ",".join(e["eventType"] for e in w["asyncEvents"])
        print(f"      - {w['name']}: {evs} → {w['targetUrl']} active={w['isActive']}")
    if len(active_wh) != 6:
        fail(f"ожидал 6 active webhooks, получил {len(active_wh)}")
    return app


def verify_redis_token() -> None:
    step("Verify token сохранён в Redis (APL)")
    keys = dc("exec", "-T", "redis", "redis-cli", "KEYS", "saleor_bridge:apl:*").strip()
    key_lines = [k for k in keys.splitlines() if k.startswith("saleor_bridge:apl:")]
    if not key_lines:
        fail("в Redis нет ключа saleor_bridge:apl:* — /register не отработал")
    for k in key_lines:
        ok(f"redis key: {k}")
    val = dc("exec", "-T", "redis", "redis-cli", "GET", key_lines[0]).strip()
    try:
        parsed = json.loads(val)
        ok(f"token_len={len(parsed.get('token',''))} domain={parsed.get('domain','')!r}")
    except json.JSONDecodeError:
        print(f"      raw: {val[:120]}")


def create_customer(token: str) -> tuple[str, str]:
    step("Trigger CUSTOMER_CREATED (customerCreate)")
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    email = f"smoke-test-{ts}@example.com"
    m = """mutation($e:String!){ customerCreate(input:{
        email:$e, firstName:"Smoke", lastName:"Test"}){
        user{ id email firstName lastName } errors{ field message code } } }"""
    d = gql(m, token, {"e": email})
    res = d["customerCreate"]
    if res.get("errors"):
        fail(f"customerCreate errors: {res['errors']}")
    user = res["user"]
    ok(f"customer создан: {user['email']} id={user['id']}")
    return email, user["id"]


def check_middleware_logs() -> None:
    step("Verify middleware logs (webhook received + signature valid)")
    logs = dc("logs", "--tail=80", "middleware")
    hits = [l for l in logs.splitlines() if "webhook_received" in l and "CUSTOMER_CREATED" in l]
    if not hits:
        # fallback: signature_valid отдельной строкой
        hits = [l for l in logs.splitlines() if "webhook_received" in l]
    if not hits:
        print(logs[-2000:])
        fail("нет webhook_received в логах middleware")
    for l in hits[-3:]:
        print(f"      {l.strip()[:200]}")
    if not any("signature_valid" in l and ("True" in l or "true" in l) for l in hits):
        fail("signature_valid=True не найдено в webhook_received")
    ok("webhook_received + signature_valid=True")


def check_worker_logs() -> None:
    step("Verify worker logs (customer_synced)")
    logs = dc("logs", "--tail=80", "middleware-worker")
    hits = [l for l in logs.splitlines() if "customer_synced" in l]
    if not hits:
        print(logs[-2000:])
        fail("нет customer_synced в логах worker")
    for l in hits[-3:]:
        print(f"      {l.strip()[:200]}")
    ok("customer_synced найден")


def update_customer(token: str, user_id: str) -> None:
    step("Idempotency: customerUpdate → CUSTOMER_UPDATED")
    # note меняется каждый прогон → Saleor видит реальное изменение и шлёт
    # CUSTOMER_UPDATED. firstName/lastName неизменны → partner.name = 'Smoke Test'.
    note = f"smoke {datetime.now().strftime('%Y%m%d%H%M%S')}"
    m = """mutation($id:ID!,$note:String){ customerUpdate(id:$id, input:{
        firstName:"Smoke", lastName:"Test", note:$note}){
        user{ id } errors{ field message code } } }"""
    d = gql(m, token, {"id": user_id, "note": note})
    res = d["customerUpdate"]
    if res.get("errors"):
        fail(f"customerUpdate errors: {res['errors']}")
    ok("customerUpdate отправлен (CUSTOMER_UPDATED)")


def main() -> int:
    ap = argparse.ArgumentParser(description="Saleor→Middleware→Odoo smoke test")
    ap.add_argument("--keep-app", action="store_true", help="не удалять Saleor App в конце")
    args = ap.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    cfg = load_config()
    odoo = connect_odoorpc(cfg, db=cfg.db_name)

    check_health()
    token = get_admin_token()
    delete_existing_apps(token)
    install_app(token)
    verify_app(token)
    verify_redis_token()

    email, user_id = create_customer(token)

    print("\n  ⏳ ждём worker (6s)…")
    time.sleep(6)
    check_middleware_logs()
    check_worker_logs()

    step("Verify Odoo state (verify_smoke)")
    partner_id, binding_id, last_in_before = verify(odoo, email)
    ok(f"partner_id={partner_id} binding_id={binding_id} last_sync_in={last_in_before}")

    # ── idempotency ──
    update_customer(token, user_id)
    print("\n  ⏳ ждём worker (6s)…")
    time.sleep(6)
    Partner = odoo.env["res.partner"]
    dup = Partner.search([("email", "=ilike", email), ("parent_id", "=", False)])
    if len(dup) != 1:
        fail(f"idempotency нарушена: partner'ов с email={email}: {len(dup)} (ожидал 1)")
    ok(f"дублей нет — 1 partner с email={email}")
    Binding = odoo.env["saleor.binding"]
    b = Binding.browse(Binding.search([("model_name", "=", "res.partner"), ("odoo_id", "=", dup[0])])[0])
    last_in_after = str(b.last_sync_in)
    if last_in_after <= last_in_before:
        print(f"      WARN: last_sync_in не продвинулся ({last_in_before} → {last_in_after})")
    else:
        ok(f"last_sync_in обновился: {last_in_before} → {last_in_after}")

    # ── cleanup ──
    if not args.keep_app:
        delete_existing_apps(token)
        ok("Saleor App удалён")
    else:
        ok("--keep-app: App оставлен")

    print(f"\n{GREEN}✅ SMOKE TEST PASSED — Saleor→Middleware→Odoo end-to-end OK{RESET}")
    print(f"   partner_id={partner_id} binding_id={binding_id} email={email}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n^C")
        sys.exit(130)
