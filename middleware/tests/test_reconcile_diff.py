"""Drift detection в reconcile (ADR-0018). Чистая diff_stock — без I/O."""

from __future__ import annotations

from saleor_bridge.domain.stock import StockLevel
from saleor_bridge.usecases.reconcile_stocks import diff_stock


def _lvl(sku: str, raw: int, buffer: int = 1) -> StockLevel:
    return StockLevel(variant_sku=sku, warehouse_external_id="1", raw_quantity=raw, safety_buffer=buffer)


def test_buffer_diff_is_not_drift():
    # Odoo 12, buffer 1 → expected 11. Saleor 11 → OK (diff -1 норма).
    rows = diff_stock(
        {"SKU-001": _lvl("SKU-001", 12)},
        {"SKU-001": {"variant_id": "V1", "total": 11, "track": True}},
        "wh-1",
    )
    assert len(rows) == 1
    r = rows[0]
    assert r.drift is False
    assert r.expected == 11
    assert r.diff == -1


def test_real_drift_detected():
    # Odoo 20 → expected 19. Saleor 15 → DRIFT.
    rows = diff_stock(
        {"SKU-005": _lvl("SKU-005", 20)},
        {"SKU-005": {"variant_id": "V5", "total": 15, "track": True}},
        "wh-1",
    )
    r = rows[0]
    assert r.drift is True
    assert r.odoo_raw == 20
    assert r.saleor_qty == 15
    assert r.expected == 19
    assert r.diff == -5


def test_inflated_saleor_is_drift():
    # Saleor вручную задрали до 999 (hardening S5) → DRIFT.
    rows = diff_stock(
        {"SKU-009": _lvl("SKU-009", 10)},
        {"SKU-009": {"variant_id": "V9", "total": 999, "track": True}},
        "wh-1",
    )
    assert rows[0].drift is True
    assert rows[0].expected == 9


def test_variant_not_in_saleor_skipped():
    rows = diff_stock({"SKU-X": _lvl("SKU-X", 5)}, {}, "wh-1")
    assert rows == []


def test_sorted_and_counts():
    odoo = {"B": _lvl("B", 5), "A": _lvl("A", 5)}
    saleor = {
        "A": {"variant_id": "VA", "total": 4, "track": True},   # OK
        "B": {"variant_id": "VB", "total": 0, "track": True},   # DRIFT (expected 4)
    }
    rows = diff_stock(odoo, saleor, "wh-1")
    assert [r.sku for r in rows] == ["A", "B"]  # sorted
    assert sum(r.drift for r in rows) == 1
