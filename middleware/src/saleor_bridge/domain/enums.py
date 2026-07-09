"""Domain enums — platform-independent."""

from __future__ import annotations

from enum import Enum


class OrderStatus(str, Enum):
    """Наш внутренний статус заказа. Маппится в sale.order.state."""

    DRAFT = "draft"        # placed, not paid — sale.order draft
    CONFIRMED = "confirmed"  # paid — sale.order action_confirm → 'sale'
    CANCELLED = "cancelled"  # cancelled — sale.order _action_cancel → 'cancel'


class SyncState(str, Enum):
    """Состояние синхронизации записи (зеркалит saleor.binding.sync_state)."""

    PENDING = "pending"
    SYNCED = "synced"
    FAILED = "failed"
    DIVERGED = "diverged"


class AddressKind(str, Enum):
    BILLING = "invoice"   # совпадает с res.partner.type
    SHIPPING = "delivery"
    OTHER = "other"
