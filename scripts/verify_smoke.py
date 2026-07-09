#!/usr/bin/env python3
"""Проверка Odoo state после smoke: CUSTOMER_CREATED → res.partner + saleor.binding.

    python scripts/verify_smoke.py                       # последний smoke-test-% partner
    python scripts/verify_smoke.py --email a@b.com       # конкретный email

Возвращает exit 0 если все assertions прошли. Переиспользуется из smoke_test.py
через verify(odoo, email).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import odoorpc  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from lib.client import connect_odoorpc, load_config  # noqa: E402

DEFAULT_EMAIL_PATTERN = "smoke-test-%@example.com"


def verify(odoo: odoorpc.ODOO, email: str | None = None) -> tuple[int, int, str]:
    """Проверить partner+binding. Возвращает (partner_id, binding_id, last_sync_in).

    Бросает AssertionError если что-то не сошлось.
    """
    Partner = odoo.env["res.partner"]
    pattern = email or DEFAULT_EMAIL_PATTERN
    ids = Partner.search([("email", "=ilike", pattern), ("parent_id", "=", False)])
    assert ids, f"res.partner не найден по email ~ {pattern!r}"
    partner = Partner.browse(ids[-1])  # последний
    print(
        f"  partner id={partner.id} name={partner.name!r} "
        f"email={partner.email} customer_rank={partner.customer_rank}"
    )
    assert partner.name == "Smoke Test", f"ожидал name='Smoke Test', получил {partner.name!r}"
    assert partner.customer_rank == 1, f"ожидал customer_rank=1, получил {partner.customer_rank}"

    Binding = odoo.env["saleor.binding"]
    bids = Binding.search([("model_name", "=", "res.partner"), ("odoo_id", "=", partner.id)])
    assert len(bids) == 1, f"ожидал 1 saleor.binding, нашёл {len(bids)}"
    b = Binding.browse(bids[0])
    print(
        f"  binding id={b.id} saleor_id={b.saleor_id!r} "
        f"sync_state={b.sync_state} last_sync_in={b.last_sync_in}"
    )
    assert b.sync_state == "synced", f"ожидал sync_state='synced', получил {b.sync_state}"
    assert b.saleor_id, "saleor_id пуст"
    return partner.id, b.id, str(b.last_sync_in)


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify Odoo state after smoke test")
    ap.add_argument("--email", default=None, help="точный email (default: последний smoke-test-%)")
    args = ap.parse_args()

    load_dotenv(HERE.parent / ".env")
    cfg = load_config()
    odoo = connect_odoorpc(cfg, db=cfg.db_name)

    try:
        partner_id, binding_id, _ = verify(odoo, args.email)
    except AssertionError as e:
        print(f"\n❌ verify failed: {e}", file=sys.stderr)
        return 1
    print(f"\n✅ E2E success: partner_id={partner_id}, binding_id={binding_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
