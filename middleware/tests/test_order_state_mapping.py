"""Odoo sale.order.state → Saleor действие (ADR-0019). Pure decide_order_action."""

from __future__ import annotations

import pytest

from saleor_bridge.usecases.sync_order_status_to_saleor import decide_order_action


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("sale", "confirm"),
        ("cancel", "cancel"),
        ("draft", None),    # ещё не оплачен → no-op
        ("done", None),     # locked → no Saleor аналога
        (None, None),
        ("weird", None),
    ],
)
def test_decide_order_action(state, expected):
    assert decide_order_action(state) == expected
