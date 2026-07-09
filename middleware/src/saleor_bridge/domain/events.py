"""Domain events — platform-independent wrappers passed to usecases."""

from __future__ import annotations

from pydantic import BaseModel

from saleor_bridge.domain.customer import Customer
from saleor_bridge.domain.order import Order


class CustomerCreatedEvent(BaseModel):
    customer: Customer


class CustomerUpdatedEvent(BaseModel):
    customer: Customer


class OrderCreatedEvent(BaseModel):
    order: Order


class OrderPaidEvent(BaseModel):
    order: Order


class OrderCancelledEvent(BaseModel):
    order: Order
