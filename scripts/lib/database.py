"""Управление базами через /web/database/* endpoints + odoorpc.db."""

from __future__ import annotations

import time

import odoorpc

from .client import Config, http_session


def list_databases(cfg: Config) -> list[str]:
    """Список БД через odoorpc.db (он зовёт XML/JSON-RPC db.list)."""
    odoo = odoorpc.ODOO(cfg.host, protocol=cfg.protocol, port=cfg.port)
    return list(odoo.db.list())


def database_exists(cfg: Config, name: str) -> bool:
    return name in list_databases(cfg)


def drop_database(cfg: Config, name: str) -> None:
    """Удалить БД. Сначала пробуем web-endpoint, потом odoorpc.db.drop как fallback."""
    print(f"  → drop database '{name}'")
    s = http_session(cfg)
    r = s.post(
        f"{cfg.url}/web/database/drop",
        data={"master_pwd": cfg.master_password, "name": name},
        allow_redirects=False,
        timeout=120,
    )
    if r.status_code in (200, 303):
        if not database_exists(cfg, name):
            return
    # Fallback на JSON-RPC.
    odoo = odoorpc.ODOO(cfg.host, protocol=cfg.protocol, port=cfg.port)
    odoo.db.drop(cfg.master_password, name)
    if database_exists(cfg, name):
        raise RuntimeError(f"не удалось удалить БД '{name}' (она всё ещё в списке)")


def create_database(cfg: Config, name: str, *, demo: bool = False, lang: str = "ru_RU", country: str = "uz") -> None:
    """Создать БД через /web/database/create (HTML form)."""
    print(f"  → create database '{name}' (lang={lang}, country={country}, demo={demo})")
    s = http_session(cfg)
    data = {
        "master_pwd": cfg.master_password,
        "name": name,
        "login": cfg.admin_login,
        "password": cfg.admin_user_password,
        "phone": "",
        "lang": lang,
        "country_code": country,
        "create_admin_user": "true",
    }
    if demo:
        data["demo"] = "true"
    r = s.post(
        f"{cfg.url}/web/database/create",
        data=data,
        allow_redirects=False,
        timeout=300,
    )
    if r.status_code not in (200, 303):
        raise RuntimeError(f"create_database HTTP {r.status_code}: {r.text[:500]}")
    deadline = time.time() + 180
    while time.time() < deadline:
        if database_exists(cfg, name):
            return
        time.sleep(2)
    raise RuntimeError(f"БД '{name}' не появилась в списке за 180с после create")
