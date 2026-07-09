"""Topological sort of categories: parents come before children."""

from __future__ import annotations

import pytest

from saleor_bridge.domain.category import ProductCategory
from saleor_bridge.usecases.bulk_seed import CategoryCycle, topological_sort


def _cat(eid: str, parent: str | None) -> ProductCategory:
    return ProductCategory(external_id=eid, name=f"c{eid}", parent_external_id=parent)


def _pos(order: list[ProductCategory]) -> dict[str, int]:
    return {c.external_id: i for i, c in enumerate(order)}


def test_parents_before_children():
    cats = [
        _cat("3", "2"),   # grandchild
        _cat("1", None),  # root
        _cat("2", "1"),   # child
    ]
    order = topological_sort(cats)
    pos = _pos(order)
    assert pos["1"] < pos["2"] < pos["3"]
    assert len(order) == 3


def test_multiple_roots_and_siblings():
    cats = [
        _cat("10", "1"), _cat("11", "1"),
        _cat("1", None), _cat("2", None),
        _cat("20", "2"),
    ]
    order = topological_sort(cats)
    pos = _pos(order)
    assert pos["1"] < pos["10"] and pos["1"] < pos["11"]
    assert pos["2"] < pos["20"]


def test_parent_outside_set_is_ignored():
    # parent "99" is not in the set — we don't fail, we just don't wait for it.
    cats = [_cat("5", "99")]
    order = topological_sort(cats)
    assert [c.external_id for c in order] == ["5"]


def test_cycle_raises():
    cats = [_cat("1", "2"), _cat("2", "1")]
    with pytest.raises(CategoryCycle):
        topological_sort(cats)
