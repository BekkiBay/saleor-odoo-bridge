"""Кастомизация UI: наследованные ir.ui.view.

Добавляем колонку 'Категория товаров' в list-вид product.template, чтобы
оператор видел путь категории прямо в списке /odoo/inventory/products.
"""

from __future__ import annotations

import odoorpc


VIEW_NAME = "marketplace.product_template_tree_with_category"

# В стандартной view product.template.product.list поле categ_id уже объявлено
# с optional="hide" — пользователь может показать через переключатель колонок.
# Меняем атрибут на "show", чтобы колонка появлялась сразу.
ARCH = """<data>
  <xpath expr="//field[@name='categ_id']" position="attributes">
    <attribute name="optional">show</attribute>
  </xpath>
</data>"""


def _resolve_parent_view_id(odoo: odoorpc.ODOO) -> int:
    """Найти базовую tree/list-view для product.template.

    Имя у разных версий может отличаться:
      - product.product_template_tree_view (Odoo 15–16)
      - product.product_template_view_tree (Odoo 17+)
    """
    candidates = [
        ("product", "product_template_tree_view"),
        ("product", "product_template_view_tree"),
    ]
    Data = odoo.env["ir.model.data"]
    for module, name in candidates:
        ids = Data.search([("module", "=", module), ("name", "=", name)])
        if ids:
            res_id = Data.read(ids[0], ["res_id"])[0]["res_id"]
            return res_id
    raise RuntimeError(
        "не нашёл базовую view product.template (tried: "
        + ", ".join(f"{m}.{n}" for m, n in candidates) + ")"
    )


def ensure_category_in_product_list(odoo: odoorpc.ODOO) -> int:
    """Создать или обновить наследованный list-вид с категорией.

    Идемпотентно: если view с таким именем уже есть — обновляем arch
    (на случай если в коде поменялся ARCH между прогонами).
    """
    View = odoo.env["ir.ui.view"]
    parent_id = _resolve_parent_view_id(odoo)
    existing = View.search([("name", "=", VIEW_NAME)])
    if existing:
        rec = View.browse(existing[0])
        # arch_db хранится с шаблонным wrapping, поэтому сравниваем grubbo
        # просто всегда write — это no-op если arch уже такой же.
        rec.write({"arch_base": ARCH, "inherit_id": parent_id, "priority": 99, "active": True})
        print(f"  ✓ view '{VIEW_NAME}' обновлён (id={existing[0]})")
        return existing[0]
    new_id = View.create({
        "name": VIEW_NAME,
        "model": "product.template",
        "inherit_id": parent_id,
        "arch_base": ARCH,
        "priority": 99,
    })
    print(f"  → создал view '{VIEW_NAME}' (inherit_id={parent_id}) → id={new_id}")
    return new_id
