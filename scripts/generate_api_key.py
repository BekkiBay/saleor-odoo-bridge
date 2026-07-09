#!/usr/bin/env python3
"""Сгенерировать Odoo API key для middleware (scope=NULL, 3 месяца).

Воспроизводимая замена ручного `odoo shell`. Создаёт ключ для пользователя
admin@marketplace.local, печатает `BRIDGE_ODOO_API_KEY=<key>` и (по умолчанию)
переписывает строку BRIDGE_ODOO_API_KEY в .env.

    python scripts/generate_api_key.py                # сгенерить + записать в .env
    python scripts/generate_api_key.py --no-write     # только напечатать

Детали:
- scope=None → ключ работает для любого RPC, нужен для JSON-2 REST API
  middleware (Authorization: bearer <key>). НЕ 'rpc'.
- expiration = now + 3 месяца. Дата создания → docs/runbooks/api-key-rotation.md.
- _generate привязывает ключ к self.env.user → выполняем with_user(admin).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
ADMIN_LOGIN = "admin@marketplace.local"
KEY_NAME = "saleor-bridge-smoke"
MARKER = "BRIDGE_ODOO_API_KEY_MARKER="

# Код выполняется внутри `odoo shell` (есть env, odoo). fields НЕ авто-импортится
# → берём odoo.fields. relativedelta из dateutil (в окружении Odoo есть).
SHELL_CODE = f"""
from dateutil.relativedelta import relativedelta
admin = env['res.users'].search([('login', '=', '{ADMIN_LOGIN}')], limit=1)
assert admin, 'user {ADMIN_LOGIN} not found'
# Снести старые smoke-ключи этого юзера (идемпотентность).
env['res.users.apikeys'].sudo().search([
    ('user_id', '=', admin.id),
    ('name', '=', '{KEY_NAME}'),
]).unlink()
exp = odoo.fields.Datetime.now() + relativedelta(months=3)
key = env['res.users.apikeys'].with_user(admin)._generate(None, '{KEY_NAME}', exp)
env.cr.commit()
print('{MARKER}' + key)
"""


def run_shell() -> str:
    """Выполнить SHELL_CODE в odoo shell, вернуть сгенерированный ключ."""
    cmd = [
        "docker", "compose", "exec", "-T", "odoo",
        "odoo", "shell", "-d", "marketplace", "--no-http", "-c", "/tmp/odoo.conf",
    ]
    proc = subprocess.run(
        cmd, input=SHELL_CODE, capture_output=True, text=True,
        cwd=str(PROJECT_ROOT), check=False,
    )
    combined = proc.stdout + "\n" + proc.stderr
    for line in combined.splitlines():
        if line.startswith(MARKER):
            return line[len(MARKER):].strip()
    print("ERROR: маркер ключа не найден в выводе odoo shell.", file=sys.stderr)
    print("─── stdout ───\n" + proc.stdout, file=sys.stderr)
    print("─── stderr ───\n" + proc.stderr, file=sys.stderr)
    sys.exit(1)


def write_env(key: str) -> None:
    """Заменить (или добавить) строку BRIDGE_ODOO_API_KEY в .env."""
    line = f"BRIDGE_ODOO_API_KEY={key}"
    if not ENV_PATH.exists():
        print(f"ERROR: .env не найден: {ENV_PATH}", file=sys.stderr)
        sys.exit(1)
    text = ENV_PATH.read_text()
    if re.search(r"^BRIDGE_ODOO_API_KEY=.*$", text, flags=re.MULTILINE):
        text = re.sub(r"^BRIDGE_ODOO_API_KEY=.*$", line, text, flags=re.MULTILINE)
    else:
        text = text.rstrip("\n") + "\n" + line + "\n"
    ENV_PATH.write_text(text)
    print(f"  ✓ .env обновлён ({ENV_PATH})", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Odoo API key for middleware")
    parser.add_argument("--no-write", action="store_true", help="не писать в .env")
    args = parser.parse_args()

    key = run_shell()
    if not re.fullmatch(r"[0-9a-f]{40}", key):
        print(f"WARNING: ключ не похож на 40-hex: {key!r}", file=sys.stderr)
    if not args.no_write:
        write_env(key)
    # На stdout — только присваивание, чтобы можно было eval/source.
    print(f"BRIDGE_ODOO_API_KEY={key}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
