#!/bin/bash
set -euo pipefail

CONFIG_SRC="/etc/odoo/odoo.conf"
CONFIG_DST="/tmp/odoo.conf"

python3 - "$CONFIG_SRC" "$CONFIG_DST" <<'PY'
import os, sys, re
src, dst = sys.argv[1], sys.argv[2]
with open(src) as f:
    content = f.read()
def sub(m):
    return os.environ.get(m.group(1), m.group(0))
content = re.sub(r"\$\{([A-Z_][A-Z0-9_]*)\}", sub, content)
with open(dst, "w") as f:
    f.write(content)
PY

chmod 640 "$CONFIG_DST" || true
exec "$@" -c "$CONFIG_DST"
