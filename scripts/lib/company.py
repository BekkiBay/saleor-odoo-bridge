"""Настройка res.company + языка admin-пользователя."""

from __future__ import annotations

import odoorpc


def _find_or_activate_currency(odoo: odoorpc.ODOO, code: str, symbol: str | None = None) -> int:
    """Найти валюту по коду; если она inactive — активировать. Возвращает id.

    Если передан symbol — обновить, если отличается. Нужно потому что в Odoo
    у UZS по умолчанию symbol='лв' (легаси), а корректный — 'сўм'.
    """
    Currency = odoo.env["res.currency"]
    Currency = Currency.with_context(active_test=False)
    ids = Currency.search([("name", "=", code)])
    if not ids:
        raise RuntimeError(f"валюта {code} не найдена в res.currency")
    rec = Currency.browse(ids[0])
    if not rec.active:
        rec.active = True
        print(f"  → активировал валюту {code}")
    if symbol is not None and rec.symbol != symbol:
        old = rec.symbol
        rec.symbol = symbol
        print(f"  → обновил symbol валюты {code}: {old!r} → {symbol!r}")
    return ids[0]


def _find_country(odoo: odoorpc.ODOO, code: str) -> int:
    Country = odoo.env["res.country"]
    ids = Country.search([("code", "=", code.upper())])
    if not ids:
        raise RuntimeError(f"страна с кодом {code} не найдена")
    return ids[0]


CURRENCY_SYMBOLS = {"UZS": "сўм"}


def configure_company(odoo: odoorpc.ODOO, *, name: str, currency_code: str = "UZS",
                      country_code: str = "UZ", timezone: str = "Asia/Tashkent") -> dict:
    """Настроить главную (main) компанию + язык admin-пользователя."""
    Company = odoo.env["res.company"]
    ids = Company.search([], limit=1, order="id asc")
    if not ids:
        raise RuntimeError("в БД нет ни одной res.company")
    company = Company.browse(ids[0])

    currency_id = _find_or_activate_currency(odoo, currency_code, symbol=CURRENCY_SYMBOLS.get(currency_code))
    country_id = _find_country(odoo, country_code)

    updates: dict[str, object] = {}
    if company.name != name:
        updates["name"] = name
    if company.currency_id.id != currency_id:
        updates["currency_id"] = currency_id
    if company.country_id.id != country_id:
        updates["country_id"] = country_id

    if updates:
        company.write(updates)
        print(f"  → обновил компанию: {list(updates)}")
    else:
        print(f"  ✓ компания уже настроена")

    # Таймзона хранится на пользователе, не на компании.
    User = odoo.env["res.users"]
    me_id = odoo.env.uid
    me = User.browse(me_id)
    user_updates: dict[str, object] = {}
    if me.tz != timezone:
        user_updates["tz"] = timezone
    if me.lang != "ru_RU":
        user_updates["lang"] = "ru_RU"
    if user_updates:
        me.write(user_updates)
        print(f"  → обновил пользователя {me.login}: {list(user_updates)}")
    else:
        print(f"  ✓ tz/lang пользователя {me.login} уже верные")

    return {
        "company_id": company.id,
        "company_name": name,
        "currency": currency_code,
        "country": country_code,
        "tz": timezone,
    }
