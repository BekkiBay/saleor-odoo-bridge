"""Создание дерева product.category из колонки 'Категория товаров' (xlsx).

Формат строки: 'Одежда / Платья' — разделитель ' / '. Поддерживается любая
глубина, на практике у нас всегда 2 уровня.
"""

from __future__ import annotations

import odoorpc


SEP = " / "


def _get_or_create_category(odoo: odoorpc.ODOO, name: str, parent_id: int | None) -> int:
    Cat = odoo.env["product.category"]
    domain = [("name", "=", name)]
    if parent_id is None:
        domain.append(("parent_id", "=", False))
    else:
        domain.append(("parent_id", "=", parent_id))
    ids = Cat.search(domain)
    if ids:
        return ids[0]
    vals = {"name": name}
    if parent_id is not None:
        vals["parent_id"] = parent_id
    new_id = Cat.create(vals)
    print(f"    + category '{name}' (parent_id={parent_id}) → id={new_id}")
    return new_id


def build_category_tree(odoo: odoorpc.ODOO, paths: list[str]) -> dict[str, int]:
    """Создать все необходимые категории. Возвращает {full_path: leaf_category_id}."""
    mapping: dict[str, int] = {}
    unique = sorted(set(paths), key=lambda s: (s.count(SEP), s))

    for full in unique:
        parts = [p.strip() for p in full.split(SEP) if p.strip()]
        parent_id: int | None = None
        for part in parts:
            parent_id = _get_or_create_category(odoo, part, parent_id)
        mapping[full] = parent_id

    return mapping
