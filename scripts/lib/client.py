"""Thin wrapper around odoorpc plus helpers for what the JSON-RPC API cannot do.

Database management (drop/create/list) goes through the /web/database/* web
endpoints rather than JSON-RPC, so we drive those with `requests` alongside.
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
    currency_code: str
    country_code: str
    timezone: str
    lang: str

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
    """Read the config from the environment (assumes .env is already loaded)."""
    required = [
        "ODOO_URL",
        "ODOO_DB_NAME",
        "ODOO_ADMIN_LOGIN",
        "ODOO_ADMIN_USER_PASSWORD",
        "ODOO_ADMIN_PASSWORD",
    ]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"ERROR: missing variables in .env: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    return Config(
        url=os.environ["ODOO_URL"],
        db_name=os.environ["ODOO_DB_NAME"],
        admin_login=os.environ["ODOO_ADMIN_LOGIN"],
        admin_user_password=os.environ["ODOO_ADMIN_USER_PASSWORD"],
        master_password=os.environ["ODOO_ADMIN_PASSWORD"],
        company_name=os.environ.get("ODOO_COMPANY_NAME", "My Company"),
        currency_code=os.environ.get("ODOO_CURRENCY", "USD"),
        country_code=os.environ.get("ODOO_COUNTRY", "US"),
        timezone=os.environ.get("ODOO_TIMEZONE", "UTC"),
        lang=os.environ.get("ODOO_LANG", "en_US"),
    )


def connect_odoorpc(cfg: Config, db: str | None = None) -> odoorpc.ODOO:
    """Create an odoorpc client. Logs in immediately when `db` is given."""
    odoo = odoorpc.ODOO(cfg.host, protocol=cfg.protocol, port=cfg.port)
    if db:
        try:
            odoo.login(db, cfg.admin_login, cfg.admin_user_password)
        except Exception as e:  # noqa: BLE001
            print(
                f"ERROR: could not log in to {db} as {cfg.admin_login}.\n"
                f"       Check ODOO_ADMIN_LOGIN / ODOO_ADMIN_USER_PASSWORD in .env.\n"
                f"       Underlying: {e}",
                file=sys.stderr,
            )
            raise
    return odoo


def http_session(cfg: Config) -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = "odoo-setup-script/1.0"
    return s
