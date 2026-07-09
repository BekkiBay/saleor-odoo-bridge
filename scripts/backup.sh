#!/usr/bin/env bash
# Бэкап: pg_dump + tar.gz filestore из volume odoo-web-data.
# Использование:
#   ./scripts/backup.sh [db_name]
# Defaults to $ODOO_DB_NAME, or "odoo".

set -euo pipefail

cd "$(dirname "$0")/.."

DB_NAME="${1:-${ODOO_DB_NAME:-odoo}}"
TS="$(date +%Y-%m-%d_%H-%M)"
BACKUP_DIR="./backups/${TS}"

if [[ ! -f .env ]]; then
    echo "ERROR: .env не найден. Скопируй .env.example в .env." >&2
    exit 1
fi
# shellcheck disable=SC1091
set -a; source .env; set +a

mkdir -p "$BACKUP_DIR"

echo "==> pg_dump '${DB_NAME}' → ${BACKUP_DIR}/db.dump"
docker compose exec -T db \
    pg_dump -U "$POSTGRES_USER" -d "$DB_NAME" -Fc \
    > "${BACKUP_DIR}/db.dump"

PROJECT="$(basename "$PWD" | tr '[:upper:]' '[:lower:]' | tr -cd '[:alnum:]_-')"
VOLUME="${PROJECT}_odoo-web-data"

echo "==> tar filestore (${VOLUME}) → ${BACKUP_DIR}/filestore.tar.gz"
docker run --rm \
    -v "${VOLUME}":/data:ro \
    -v "$(pwd)/${BACKUP_DIR}":/backup \
    alpine:3 \
    tar czf /backup/filestore.tar.gz -C /data .

echo "==> Done: ${BACKUP_DIR}"
ls -lh "$BACKUP_DIR"
