"""Domain enums — platform-independent."""

from __future__ import annotations

from enum import StrEnum


class OrderStatus(StrEnum):
    """Our internal order status. Maps to sale.order.state."""

    DRAFT = "draft"        # placed, not paid — sale.order draft
    CONFIRMED = "confirmed"  # paid — sale.order action_confirm → 'sale'
    CANCELLED = "cancelled"  # cancelled — sale.order _action_cancel → 'cancel'


class SyncState(StrEnum):
    """Sync state of a record (mirrors saleor.binding.sync_state)."""

    PENDING = "pending"
    SYNCED = "synced"
    FAILED = "failed"
    DIVERGED = "diverged"


class AddressKind(StrEnum):
    BILLING = "invoice"   # matches res.partner.type
    SHIPPING = "delivery"
    OTHER = "other"
