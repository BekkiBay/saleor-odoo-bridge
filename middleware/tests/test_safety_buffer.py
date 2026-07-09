"""Safety buffer MAX(raw - buffer, 0) (ADR-0016)."""

from __future__ import annotations

import pytest

from saleor_bridge.domain.stock import StockLevel


def _level(raw: int, buffer: int = 1) -> StockLevel:
    return StockLevel(
        variant_sku="SKU", warehouse_external_id="1", raw_quantity=raw, safety_buffer=buffer
    )


@pytest.mark.parametrize(
    ("raw", "buffer", "expected"),
    [
        (20, 1, 19),
        (15, 1, 14),
        (2, 1, 1),
        (1, 1, 0),   # последняя единица → «нет в наличии» (anti-oversell)
        (0, 1, 0),
        (5, 0, 5),   # buffer=0 → как есть
        (1, 0, 1),
        (100, 5, 95),
    ],
)
def test_available_after_buffer(raw, buffer, expected):
    assert _level(raw, buffer).available_quantity == expected


def test_display_quantity_is_available():
    lvl = _level(15, 1)
    assert lvl.display_quantity == lvl.available_quantity == 14
