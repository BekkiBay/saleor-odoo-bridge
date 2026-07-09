"""Тонкая обёртка над odoorpc + helpers для нечего-делать в JSON-RPC API.

Управление БД (drop/create/list) идёт через web-endpoints /web/database/*,
а не через JSON-RPC — поэтому работаем с requests параллельно.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from urllib.parse import urlparse

import odoorpc
import requests


@dataclass
class Config:
    url: str
    db_name: str
    admin_login: str
    admin_user_password: str
    master_password: str
    company_name: str

    @property
    def host(self) -> str:
        return urlparse(self.url).hostname or "localhost"

    @property
    def port(self) -> int:
        p = urlparse(self.url).port
        if p:
            return p
        return 443 if urlparse(self.url).scheme == "https" else 80

    @property
    def protocol(self) -> str:
        return "jsonrpc+ssl" if urlparse(self.url).scheme == "https" else "jsonrpc"


def load_config() -> Config:
    """Читает конфиг из окружения (предполагается, что .env уже загружен)."""
    required = [
        "ODOO_URL",
        "ODOO_DB_NAME",
        "ODOO_ADMIN_LOGIN",
        "ODOO_ADMIN_USER_PASSWORD",
        "ODOO_ADMIN_PASSWORD",
    ]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"ERROR: в .env не хватает переменных: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    return Config(
        url=os.environ["ODOO_URL"],
        db_name=os.environ["ODOO_DB_NAME"],
        admin_login=os.environ["ODOO_ADMIN_LOGIN"],
        admin_user_password=os.environ["ODOO_ADMIN_USER_PASSWORD"],
        master_password=os.environ["ODOO_ADMIN_PASSWORD"],
        company_name=os.environ.get("ODOO_COMPANY_NAME", "Marketplace UZ"),
    )


def connect_odoorpc(cfg: Config, db: str | None = None) -> odoorpc.ODOO:
    """Создаёт odoorpc-клиент. Если db передана — сразу логинимся."""
    odoo = odoorpc.ODOO(cfg.host, protocol=cfg.protocol, port=cfg.port)
    if db:
        try:
            odoo.login(db, cfg.admin_login, cfg.admin_user_password)
        except Exception as e:  # noqa: BLE001
            print(
                f"ERROR: не получилось залогиниться в {db} как {cfg.admin_login}.\n"
                f"       Проверь ODOO_ADMIN_LOGIN / ODOO_ADMIN_USER_PASSWORD в .env.\n"
                f"       Underlying: {e}",
                file=sys.stderr,
            )
            raise
    return odoo


def http_session(cfg: Config) -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = "odoo-setup-script/1.0"
    return s
