"""Standalone unit test for the pure fulfillment_status mapping (no Odoo runtime).

Imports the module by file path so it runs under plain pytest without Odoo on
the path — fulfillment_status.py has zero Odoo imports by design.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_MOD = Path(__file__).resolve().parents[1] / "models" / "fulfillment_status.py"
_spec = importlib.util.spec_from_file_location("fulfillment_status", _MOD)
fulfillment_status = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fulfillment_status)
compute = fulfillment_status.compute_fulfillment_status


def test_draft_is_paid():
    assert compute("draft", False, False) == "paid"


def test_sale_is_assembling():
    assert compute("sale", False, False) == "assembling"


def test_done_state_is_assembling():
    assert compute("done", False, False) == "assembling"


def test_done_picking_is_shipped():
    assert compute("sale", False, True) == "shipped"


def test_delivered_flag_is_delivered():
    assert compute("sale", True, True) == "delivered"


def test_cancel_beats_everything():
    assert compute("cancel", True, True) == "cancelled"


def test_delivered_beats_shipped():
    assert compute("done", True, True) == "delivered"
