"""PTAV-assignments варианта → Saleor variant.attributes input (Phase 3.5).

resolve_attribute_input резолвит (attribute, value) пары через saleor.binding в
форму [{id, dropdownValue:{id}}]. Нет binding → AttributeBindingMissing (retry).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from saleor_bridge.adapters.odoo.binding import BindingRepository
from saleor_bridge.domain.variants import Variant, VariantAttributeAssignment
from saleor_bridge.usecases.sync_variant_to_saleor import (
    AttributeBindingMissing,
    resolve_attribute_input,
)
from tests.stock_fakes import FakeOdoo


def _variant() -> Variant:
    return Variant(
        external_id="5",
        template_external_id="1",
        sku="DRESS-001-M-RED",
        price=Decimal("150000.00"),
        attributes=[
            VariantAttributeAssignment(attribute_external_id="10", value_external_id="100"),
            VariantAttributeAssignment(attribute_external_id="11", value_external_id="110"),
        ],
    )


@pytest.mark.asyncio
async def test_resolves_to_dropdown_input():
    odoo = FakeOdoo(bindings={
        ("product.attribute", 10): "QXR0cmlidXRlOjEw",
        ("product.attribute.value", 100): "QXR0cmlidXRlVmFsdWU6MTAw",
        ("product.attribute", 11): "QXR0cmlidXRlOjEx",
        ("product.attribute.value", 110): "QXR0cmlidXRlVmFsdWU6MTEw",
    })
    out = await resolve_attribute_input(BindingRepository(odoo), _variant())
    assert out == [
        {"id": "QXR0cmlidXRlOjEw", "dropdown": {"id": "QXR0cmlidXRlVmFsdWU6MTAw"}},
        {"id": "QXR0cmlidXRlOjEx", "dropdown": {"id": "QXR0cmlidXRlVmFsdWU6MTEw"}},
    ]


@pytest.mark.asyncio
async def test_missing_value_binding_raises():
    odoo = FakeOdoo(bindings={
        ("product.attribute", 10): "QXR0cmlidXRlOjEw",
        ("product.attribute.value", 100): "QXR0cmlidXRlVmFsdWU6MTAw",
        ("product.attribute", 11): "QXR0cmlidXRlOjEx",
        # value 110 не синкнут
    })
    with pytest.raises(AttributeBindingMissing):
        await resolve_attribute_input(BindingRepository(odoo), _variant())


@pytest.mark.asyncio
async def test_empty_attributes_resolves_empty():
    # single-variant продукт без атрибутов → пустой input (миграция Phase 3.2)
    v = Variant(external_id="9", template_external_id="2", sku="SKU-009", price=Decimal("100.00"))
    out = await resolve_attribute_input(BindingRepository(FakeOdoo()), v)
    assert out == []
