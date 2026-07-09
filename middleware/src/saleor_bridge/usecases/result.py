"""SyncResult — the common return type for usecases."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SyncResult:
    ok: bool
    odoo_id: int | None = None
    message: str = ""
    warnings: list[str] = field(default_factory=list)
