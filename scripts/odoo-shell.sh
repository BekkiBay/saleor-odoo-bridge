#!/usr/bin/env bash
# Интерактивный Odoo shell (Python REPL с загруженной ORM).
# Использование:
#   ./scripts/odoo-shell.sh [db_name]
# Defaults to $ODOO_DB_NAME, or "odoo".

set -euo pipefail

cd "$(dirname "$0")/.."

DB_NAME="${1:-${ODOO_DB_NAME:-odoo}}"

exec docker compose exec odoo odoo shell -c /tmp/odoo.conf -d "$DB_NAME" --no-http
