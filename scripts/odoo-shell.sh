#!/usr/bin/env bash
# Интерактивный Odoo shell (Python REPL с загруженной ORM).
# Использование:
#   ./scripts/odoo-shell.sh [db_name]
# По умолчанию db_name=marketplace.

set -euo pipefail

cd "$(dirname "$0")/.."

DB_NAME="${1:-marketplace}"

exec docker compose exec odoo odoo shell -c /tmp/odoo.conf -d "$DB_NAME" --no-http
