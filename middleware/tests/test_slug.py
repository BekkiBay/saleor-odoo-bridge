"""Slugify + транслитерация (Phase 3.2)."""

from __future__ import annotations

from saleor_bridge.adapters.saleor.slug import slugify, transliterate, with_suffix


def test_transliterate_basic():
    assert transliterate("Платья").lower() == "platya"
    assert transliterate("Кепки").lower() == "kepki"


def test_slugify_path():
    assert slugify("Одежда / Платья") == "odezhda-platya"


def test_slugify_collapses_and_strips():
    assert slugify("  Брюки  и  джинсы  ") == "bryuki-i-dzhinsy"


def test_slugify_non_empty_fallback():
    assert slugify("!!!") == "item"


def test_with_suffix():
    assert with_suffix("platya", "7") == "platya-7"
