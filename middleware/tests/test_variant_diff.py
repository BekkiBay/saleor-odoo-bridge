"""diff_variants: desired (Odoo) vs current (Saleor) → create/keep/delete."""

from __future__ import annotations

from decimal import Decimal

from saleor_bridge.domain.variants import Variant
from saleor_bridge.usecases.sync_template_variants_to_saleor import diff_variants


def _v(sku: str) -> Variant:
    return Variant(external_id=sku, template_external_id="1", sku=sku, price=Decimal("100.00"))


def test_all_new_go_to_create():
    diff = diff_variants([_v("A"), _v("B")], {})
    assert {v.sku for v in diff.create} == {"A", "B"}
    assert diff.keep == []
    assert diff.delete == {}


def test_existing_go_to_keep():
    diff = diff_variants([_v("A")], {"A": "VARIANT_A"})
    assert {v.sku for v in diff.keep} == {"A"}
    assert diff.create == []
    assert diff.delete == {}


def test_stale_saleor_variant_deleted():
    # Migration S2: dummy "SKU-001" is no longer desired → delete (ADR-0025).
    diff = diff_variants(
        [_v("SKU-001-S"), _v("SKU-001-M")],
        {"SKU-001": "DUMMY", "SKU-001-S": "VS"},
    )
    assert {v.sku for v in diff.create} == {"SKU-001-M"}
    assert {v.sku for v in diff.keep} == {"SKU-001-S"}
    assert diff.delete == {"SKU-001": "DUMMY"}


def test_single_variant_adopt_no_delete():
    # S7: single-variant dummy SKU matched → keep (adopt), nothing gets deleted.
    diff = diff_variants([_v("SKU-007")], {"SKU-007": "DUMMY7"})
    assert {v.sku for v in diff.keep} == {"SKU-007"}
    assert diff.create == []
    assert diff.delete == {}
