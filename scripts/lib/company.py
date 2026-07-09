"""Configure res.company plus the admin user's timezone and language."""

from __future__ import annotations

import odoorpc

# Odoo ships a legacy symbol for a few currencies. Map code → the symbol you
# want written to res.currency. Extend as needed; empty means "leave as is".
CURRENCY_SYMBOL_OVERRIDES: dict[str, str] = {}


def _find_or_activate_currency(odoo: odoorpc.ODOO, code: str, symbol: str | None = None) -> int:
    """Find a currency by code, activating it when inactive. Returns its id.

    When `symbol` is given and differs, it is written — some currencies ship
    with a legacy symbol in stock Odoo.
    """
    Currency = odoo.env["res.currency"]
    Currency = Currency.with_context(active_test=False)
    ids = Currency.search([("name", "=", code)])
    if not ids:
        raise RuntimeError(f"currency {code} not found in res.currency")
    rec = Currency.browse(ids[0])
    if not rec.active:
        rec.active = True
        print(f"  → activated currency {code}")
    if symbol is not None and rec.symbol != symbol:
        old = rec.symbol
        rec.symbol = symbol
        print(f"  → updated symbol of {code}: {old!r} → {symbol!r}")
    return ids[0]


def _find_country(odoo: odoorpc.ODOO, code: str) -> int:
    Country = odoo.env["res.country"]
    ids = Country.search([("code", "=", code.upper())])
    if not ids:
        raise RuntimeError(f"country with code {code} not found")
    return ids[0]


def configure_company(
    odoo: odoorpc.ODOO,
    *,
    name: str,
    currency_code: str = "USD",
    country_code: str = "US",
    timezone: str = "UTC",
    lang: str = "en_US",
) -> dict:
    """Configure the main company plus the admin user's timezone/language."""
    Company = odoo.env["res.company"]
    ids = Company.search([], limit=1, order="id asc")
    if not ids:
        raise RuntimeError("the database has no res.company record")
    company = Company.browse(ids[0])

    currency_id = _find_or_activate_currency(
        odoo, currency_code, symbol=CURRENCY_SYMBOL_OVERRIDES.get(currency_code)
    )
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
        print(f"  → updated company: {list(updates)}")
    else:
        print("  ✓ company already configured")

    # The timezone lives on the user, not on the company.
    User = odoo.env["res.users"]
    me_id = odoo.env.uid
    me = User.browse(me_id)
    user_updates: dict[str, object] = {}
    if me.tz != timezone:
        user_updates["tz"] = timezone
    if me.lang != lang:
        user_updates["lang"] = lang
    if user_updates:
        me.write(user_updates)
        print(f"  → updated user {me.login}: {list(user_updates)}")
    else:
        print(f"  ✓ tz/lang of user {me.login} already correct")

    return {
        "company_id": company.id,
        "company_name": name,
        "currency": currency_code,
        "country": country_code,
        "tz": timezone,
        "lang": lang,
    }
