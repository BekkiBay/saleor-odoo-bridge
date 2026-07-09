"""Slugify with Cyrillic transliteration.

Saleor slugs are globally unique. Odoo names are Cyrillic and sometimes
duplicated (several "Caps", "Pajamas", "Glasses" under different parents). So:
- categories get a slug from the *full path* (`complete_name`) → unique per tree;
- products get a slug from name + SKU → unique per SKU.
Plus the caller has a retry-suffix for when Saleor still returns "slug exists".
"""

from __future__ import annotations

import re

# RU→Latin table sufficient for a clothing catalog (GOST-like, simplified).
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
    """ASCII slug: transliterate → lowercase → non-alphanumeric to `-` → collapse."""
    s = transliterate(text).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s or "item"


def with_suffix(base_slug: str, suffix: str) -> str:
    """Add a suffix to resolve a collision: `platya` + `7` → `platya-7`."""
    return f"{base_slug}-{suffix}"
