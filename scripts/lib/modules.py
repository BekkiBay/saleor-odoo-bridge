"""Установка модулей через ir.module.module.button_immediate_install."""

from __future__ import annotations

import odoorpc


REQUIRED_MODULES = ["contacts", "stock", "sale_management", "account"]


def installed_modules(odoo: odoorpc.ODOO, names: list[str]) -> dict[str, str]:
    """Возвращает {technical_name: state} для перечисленных модулей."""
    Mod = odoo.env["ir.module.module"]
    ids = Mod.search([("name", "in", names)])
    if not ids:
        return {}
    records = Mod.read(ids, ["name", "state"])
    return {r["name"]: r["state"] for r in records}


def ensure_modules(odoo: odoorpc.ODOO, names: list[str] = REQUIRED_MODULES) -> dict[str, str]:
    """Установить недостающие модули. Возвращает финальный {name: state}."""
    Mod = odoo.env["ir.module.module"]
    Mod.update_list()

    state = installed_modules(odoo, names)
    missing_in_registry = [n for n in names if n not in state]
    if missing_in_registry:
        raise RuntimeError(
            f"модули не найдены в ir.module.module: {missing_in_registry}. "
            f"Возможно, неверные technical_name для Odoo 19."
        )

    for n in names:
        if state[n] == "installed":
            print(f"  ✓ {n} уже установлен")
            continue
        print(f"  → install {n} (текущий state={state[n]})")
        ids = Mod.search([("name", "=", n)])
        Mod.browse(ids).button_immediate_install()
        Mod.update_list()
        state = installed_modules(odoo, names)
        if state[n] != "installed":
            raise RuntimeError(f"модуль {n} после install имеет state={state[n]}")

    return state
