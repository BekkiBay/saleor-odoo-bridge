"""domain.Customer / Address → res.partner operations (Odoo JSON-2)."""

from __future__ import annotations

import structlog

from saleor_bridge.domain.address import Address
from saleor_bridge.domain.customer import Customer
from saleor_bridge.odoo.client import OdooClient

log = structlog.get_logger()

_PARTNER = "res.partner"

# Cache country_id so we don't hit Odoo for every address.
_country_cache: dict[str, int | None] = {}


async def resolve_country_id(odoo: OdooClient, code: str) -> int | None:
    if not code:
        return None
    code = code.upper()
    if code in _country_cache:
        return _country_cache[code]
    rows = await odoo.search_read(
        "res.country", [("code", "=", code)], ["id"], limit=1
    )
    cid = rows[0]["id"] if rows else None
    _country_cache[code] = cid
    return cid


async def _address_vals(odoo: OdooClient, addr: Address, parent_id: int, addr_type: str) -> dict:
    return {
        "name": addr.full_name,
        "parent_id": parent_id,
        "type": addr_type,
        "street": addr.street_address_1 or False,
        "street2": addr.street_address_2 or False,
        "city": addr.city or False,
        "zip": addr.postal_code or False,
        "country_id": await resolve_country_id(odoo, addr.country_code) or False,
        "phone": addr.phone or False,
        "company_name": addr.company_name or False,
    }


async def find_partner_id(odoo: OdooClient, email: str) -> int | None:
    """Lookup top-level customer by email (case-insensitive)."""
    rows = await odoo.search_read(
        _PARTNER,
        [("email", "=ilike", email), ("parent_id", "=", False)],
        ["id"],
        limit=1,
    )
    return rows[0]["id"] if rows else None


async def upsert_partner(odoo: OdooClient, customer: Customer, *, existing_id: int | None) -> int:
    """Create or update the top-level res.partner. Returns the odoo id."""
    vals = {
        "name": customer.display_name,
        "email": str(customer.email),
        "phone": customer.phone or False,
        "customer_rank": 1,
        "is_company": False,
    }
    if existing_id:
        await odoo.write(_PARTNER, [existing_id], vals)
        partner_id = existing_id
    else:
        partner_id = await odoo.create(_PARTNER, vals)

    await _sync_child_addresses(odoo, customer, partner_id)
    return partner_id


async def _sync_child_addresses(odoo: OdooClient, customer: Customer, partner_id: int) -> None:
    """Create/update child contacts of type invoice/delivery.

    Idempotency: look up a child with the same type; if found — write, else create.
    """
    for addr, addr_type in (
        (customer.default_billing_address, "invoice"),
        (customer.default_shipping_address, "delivery"),
    ):
        if addr is None:
            continue
        vals = await _address_vals(odoo, addr, partner_id, addr_type)
        existing = await odoo.search(
            _PARTNER,
            [("parent_id", "=", partner_id), ("type", "=", addr_type)],
            limit=1,
        )
        if existing:
            await odoo.write(_PARTNER, [existing[0]], vals)
        else:
            await odoo.create(_PARTNER, vals)


async def get_child_address_id(odoo: OdooClient, partner_id: int, addr_type: str) -> int | None:
    rows = await odoo.search(
        _PARTNER,
        [("parent_id", "=", partner_id), ("type", "=", addr_type)],
        limit=1,
    )
    return rows[0] if rows else None
