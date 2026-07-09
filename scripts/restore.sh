#!/usr/bin/env bash
# Восстановление из бэкапа.
# Использование:
#   ./scripts/restore.sh <путь_к_папке_бэкапа> [db_name]

set -euo pipefail

cd "$(dirname "$0")/.."

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <backup_dir> [db_name]" >&2
    exit 1
fi

BACKUP_DIR="$1"
DB_NAME="${2:-marketplace}"

if [[ ! -f "${BACKUP_DIR}/db.dump" || ! -f "${BACKUP_DIR}/filestore.tar.gz" ]]; then
    echo "ERROR: в ${BACKUP_DIR} не хватает db.dump и/или filestore.tar.gz" >&2
    exit 1
fi

if [[ ! -f .env ]]; then
    echo "ERROR: .env не найден." >&2
    exit 1
fi
# shellcheck disable=SC1091
set -a; source .env; set +a

cat <<EOF

⚠️  ВНИМАНИЕ: Это удалит ТЕКУЩИЕ данные:
    - БД:        ${DB_NAME}
    - Filestore: volume odoo-web-data (всё содержимое)

Источник:  ${BACKUP_DIR}

EOF
read -r -p "Продолжить? Напечатай 'yes' для подтверждения: " CONFIRM
if [[ "$CONFIRM" != "yes" ]]; then
    echo "Отмена."
    exit 1
fi

echo "==> Останавливаю odoo (db остаётся жив)"
docker compose stop odoo

echo "==> Пересоздаю БД ${DB_NAME}"
docker compose exec -T db psql -U "$POSTGRES_USER" -d postgres -c \
    "DROP DATABASE IF EXISTS \"${DB_NAME}\";"
docker compose exec -T db psql -U "$POSTGRES_USER" -d postgres -c \
    "CREATE DATABASE \"${DB_NAME}\" OWNER \"${POSTGRES_USER}\";"

echo "==> pg_restore → ${DB_NAME}"
docker compose exec -T db \
    pg_restore -U "$POSTGRES_USER" -d "$DB_NAME" --no-owner --role="$POSTGRES_USER" \
    < "${BACKUP_DIR}/db.dump"

PROJECT="$(basename "$PWD" | tr '[:upper:]' '[:lower:]' | tr -cd '[:alnum:]_-')"
VOLUME="${PROJECT}_odoo-web-data"

echo "==> Очищаю filestore (${VOLUME}) и распаковываю tar.gz"
docker run --rm \
    -v "${VOLUME}":/data \
    -v "$(pwd)/${BACKUP_DIR}":/backup:ro \
    alpine:3 \
    sh -c 'rm -rf /data/* /data/.[!.]* 2>/dev/null; tar xzf /backup/filestore.tar.gz -C /data'

echo "==> Запускаю odoo"
docker compose start odoo

echo "==> Done. Жди ~30 сек и проверяй http://localhost:8069"
