"""Standalone unit test for the pure justix_status mapping (no Odoo runtime).

Imports the module by file path so it runs under plain pytest without Odoo on
the path — justix_status.py has zero Odoo imports by design.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_MOD = Path(__file__).resolve().parents[1] / "models" / "justix_status.py"
_spec = importlib.util.spec_from_file_location("justix_status", _MOD)
justix_status = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(justix_status)
compute = justix_status.compute_justix_status


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
