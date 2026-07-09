"""picking SKU→qty → Saleor FulfillmentLine[] (ADR-0019). Pure build_fulfillment_lines."""

from __future__ import annotations

from saleor_bridge.adapters.saleor.order_mutations import build_fulfillment_lines

_WH = "V2FyZWhvdXNlOjE="


def _ol(line_id, sku, to_fulfill, *, productSku=None):
    return {
        "id": line_id, "productSku": productSku if productSku is not None else sku,
        "quantity": to_fulfill, "quantityToFulfill": to_fulfill, "variant": {"sku": sku},
    }


def test_basic_mapping():
    order_lines = [_ol("L1", "SKU-001", 2), _ol("L2", "SKU-002", 1)]
    lines = build_fulfillment_lines(order_lines, {"SKU-001": 2, "SKU-002": 1}, _WH)
    assert len(lines) == 2
    by = {ln.saleor_order_line_id: ln for ln in lines}
    assert by["L1"].quantity == 2 and by["L1"].warehouse_id == _WH
    assert by["L2"].quantity == 1


def test_quantity_capped_by_to_fulfill():
    # Odoo отгрузил 5, но в Saleor к фулфиллу только 3 → берём 3
    lines = build_fulfillment_lines([_ol("L1", "SKU-001", 3)], {"SKU-001": 5}, _WH)
    assert lines[0].quantity == 3


def test_skip_already_fulfilled_line():
    # quantityToFulfill=0 → строка пропускается
    lines = build_fulfillment_lines([_ol("L1", "SKU-001", 0)], {"SKU-001": 2}, _WH)
    assert lines == []


def test_skip_unmatched_sku():
    lines = build_fulfillment_lines([_ol("L1", "SKU-001", 2)], {"SKU-999": 2}, _WH)
    assert lines == []


def test_fallback_to_variant_sku_when_no_productSku():
    line = {"id": "L1", "productSku": None, "quantityToFulfill": 2, "variant": {"sku": "SKU-007"}}
    lines = build_fulfillment_lines([line], {"SKU-007": 2}, _WH)
    assert len(lines) == 1 and lines[0].quantity == 2
