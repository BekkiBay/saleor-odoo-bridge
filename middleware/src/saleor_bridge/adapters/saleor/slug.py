"""Slugify с транслитерацией кириллицы.

Saleor slug глобально уникален. Odoo-имена кириллические и местами дублируются
(несколько «Кепки», «Пижамы», «Очки» под разными родителями). Поэтому:
- категориям даём slug из *полного пути* (`complete_name`) → уникален по дереву;
- продуктам — slug из имени + SKU → уникален по SKU.
Плюс на стороне вызова есть retry-suffix, если Saleor всё же вернул «slug exists».
"""

from __future__ import annotations

import re

# Достаточная для каталога одежды RU→Latin таблица (ГОСТ-подобная, упрощённая).
_RU_MAP = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def transliterate(text: str) -> str:
    out = []
    for ch in text:
        lower = ch.lower()
        if lower in _RU_MAP:
            mapped = _RU_MAP[lower]
            out.append(mapped.upper() if ch.isupper() else mapped)
        else:
            out.append(ch)
    return "".join(out)


def slugify(text: str) -> str:
    """ASCII slug: транслит → lowercase → не-буквенно-цифровое в `-` → схлопнуть."""
    s = transliterate(text).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s or "item"


def with_suffix(base_slug: str, suffix: str) -> str:
    """Добавить суффикс для разрешения коллизии: `platya` + `7` → `platya-7`."""
    return f"{base_slug}-{suffix}"
