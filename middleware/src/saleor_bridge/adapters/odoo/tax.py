"""Resolve Odoo sale account.tax by rate (P0 financials sync)."""
from __future__ import annotations

from decimal import Decimal

from saleor_bridge.odoo.client import OdooClient

_TAX = "account.tax"
_cache: dict[float, int] = {}


class TaxNotConfigured(RuntimeError):
    """No sale account.tax in Odoo at the required rate — config error."""


async def resolve_sale_tax(odoo: OdooClient, rate: Decimal) -> int:
    """Find a sale `account.tax` whose amount == rate (percent). Cached by rate.

    Raises TaxNotConfigured if missing — surfaced as an alert, not silently dropped.
    """
    key = float(rate)
    if key in _cache:
        return _cache[key]
    rows = await odoo.search_read(
        _TAX,
        [("type_tax_use", "=", "sale"), ("amount", "=", key)],
        ["id"],
        limit=1,
    )
    if not rows:
        raise TaxNotConfigured(f"no sale account.tax with amount={key}")
    _cache[key] = rows[0]["id"]
    return _cache[key]
