"""Outbound dispatch Odoo → middleware (Phase 3.2, reverse flow).

base.automation (on_create_or_write) → серверный action `state='code'` зовёт
`records._saleor_dispatch()`. Этот метод:
  1. уважает context `saleor_sync_skip` (guard от эхо при будущем inbound product-sync);
  2. пишет saleor.outbox (observability);
  3. POST'ит в middleware /api/odoo-events?secret=... (ADR-0011);
  4. обновляет outbox state по ответу.

POST синхронный, но короткий (middleware кладёт job в arq и сразу 200). На сбой
middleware НЕ роняем транзакцию Odoo — лишь помечаем outbox failed.
"""

import json
import logging
import os

import requests

from odoo import models

_logger = logging.getLogger(__name__)

_TIMEOUT = 2  # сек; middleware обязан ответить <1s (вся работа — в arq)


def _config(env):
    # Prefer the live container env so rotating BRIDGE_ODOO_WEBHOOK_SECRET in .env +
    # a restart takes effect immediately. ir.config_parameter is only seeded at module
    # install (post_init), so it would otherwise pin the secret to the install-time
    # value and silently desync from the middleware. Stored param is the fallback.
    icp = env["ir.config_parameter"].sudo()
    url = os.environ.get("BRIDGE_MIDDLEWARE_INTERNAL_URL") or icp.get_param(
        "saleor_sync.middleware_url", "http://middleware:8080"
    )
    secret = os.environ.get("BRIDGE_ODOO_WEBHOOK_SECRET") or icp.get_param(
        "saleor_sync.webhook_secret", ""
    )
    return url.rstrip("/"), secret


def _emit(env, model_name, odoo_id, action):
    """Один outbound-event: запись в saleor.outbox + POST в middleware.

    На сбой middleware НЕ роняем транзакцию Odoo — лишь помечаем outbox failed.
    """
    url, secret = _config(env)
    endpoint = f"{url}/api/odoo-events"
    Outbox = env["saleor.outbox"].sudo()
    body = {"odoo_model": model_name, "odoo_id": odoo_id, "action": action}
    outbox = Outbox.create({
        "model_name": model_name,
        "odoo_id": odoo_id,
        "action": action,
        "payload": json.dumps(body),
        "state": "sent",
    })
    try:
        resp = requests.post(endpoint, params={"secret": secret}, json=body, timeout=_TIMEOUT)
        outbox.response_code = resp.status_code
        if 200 <= resp.status_code < 300:
            outbox.state = "confirmed"
        else:
            outbox.state = "failed"
            outbox.error_message = resp.text[:2000]
    except Exception as exc:  # noqa: BLE001 — не роняем write пользователя
        outbox.state = "failed"
        outbox.error_message = str(exc)[:2000]
        _logger.warning("saleor dispatch failed for %s#%s: %s", model_name, odoo_id, exc)


def _dispatch(records, model_name):
    if records.env.context.get("saleor_sync_skip"):
        return
    Binding = records.env["saleor.binding"].sudo()
    for rec in records:
        has_binding = bool(
            Binding.search_count([("model_name", "=", model_name), ("odoo_id", "=", rec.id)])
        )
        action = "write" if has_binding else "create"
        _emit(records.env, model_name, rec.id, action)


def _dispatch_stock(records):
    """stock.quant write → событие per product.product (Phase 3.3, ADR-0017).

    Subject = product.product (не сам quant): middleware перечитывает агрегат
    остатка. Дедупим по товару — один write может затронуть несколько quant'ов.
    """
    if records.env.context.get("saleor_sync_skip"):
        return
    seen = set()
    for quant in records:
        pp = quant.product_id
        if not pp or pp.id in seen:
            continue
        seen.add(pp.id)
        _emit(records.env, "product.product", pp.id, "write")


def _dispatch_ptav(records):
    """PTAV.price_extra изменился → событие product.template родителя (Phase 3.5).

    Subject = шаблон (не PTAV): middleware реконсилит цены всех вариантов шаблона
    (lst_price пересчитан = list_price + price_extra). Дедупим по шаблону — один
    write может затронуть несколько PTAV.
    """
    if records.env.context.get("saleor_sync_skip"):
        return
    Binding = records.env["saleor.binding"].sudo()
    seen = set()
    for ptav in records:
        tmpl = ptav.product_tmpl_id
        if not tmpl or tmpl.id in seen:
            continue
        seen.add(tmpl.id)
        # Эмитим только для синканных шаблонов (есть binding) — ручные PTAV не пушим.
        if Binding.search_count([("model_name", "=", "product.template"), ("odoo_id", "=", tmpl.id)]):
            _emit(records.env, "product.template", tmpl.id, "write")


def _has_order_binding(env, order_id):
    return bool(env["saleor.binding"].sudo().search_count(
        [("model_name", "=", "sale.order"), ("odoo_id", "=", order_id)]
    ))


def _dispatch_order_state(records):
    """sale.order.state change → событие (Phase 3.4, ADR-0019).

    Только для значимых состояний и заказов, синканных из Saleor (есть binding) —
    чтобы не пушить вручную созданные в Odoo заказы. skip-guard (ADR-0020) рвёт эхо.
    """
    if records.env.context.get("saleor_sync_skip"):
        return
    for so in records:
        if so.state not in ("sale", "cancel", "done"):
            continue
        if not _has_order_binding(records.env, so.id):
            continue
        _emit(records.env, "sale.order", so.id, "state_change")


def _dispatch_picking_shipped(records):
    """stock.picking → done → fulfillment event (Phase 3.4, ADR-0019/0021)."""
    if records.env.context.get("saleor_sync_skip"):
        return
    for pick in records:
        if pick.state != "done" or not pick.sale_id:
            continue
        if not _has_order_binding(records.env, pick.sale_id.id):
            continue
        _emit(records.env, "stock.picking", pick.id, "shipped")


class ProductTemplate(models.Model):
    _inherit = "product.template"

    def with_saleor_skip(self):
        """Контекст-менеджер: следующий write не триггерит outbound webhook."""
        return self.with_context(saleor_sync_skip=True)

    def _saleor_dispatch(self):
        _dispatch(self, "product.template")


class ProductCategory(models.Model):
    _inherit = "product.category"

    def with_saleor_skip(self):
        return self.with_context(saleor_sync_skip=True)

    def _saleor_dispatch(self):
        _dispatch(self, "product.category")


class StockQuant(models.Model):
    _inherit = "stock.quant"

    def _saleor_dispatch_stock(self):
        _dispatch_stock(self)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def with_saleor_skip(self):
        return self.with_context(saleor_sync_skip=True)

    def _saleor_dispatch_state(self):
        _dispatch_order_state(self)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _saleor_dispatch_shipped(self):
        _dispatch_picking_shipped(self)


# ── Phase 3.5: variants & attributes ──────────────────────────────────────

class ProductAttribute(models.Model):
    _inherit = "product.attribute"

    def with_saleor_skip(self):
        return self.with_context(saleor_sync_skip=True)

    def _saleor_dispatch(self):
        _dispatch(self, "product.attribute")


class ProductAttributeValue(models.Model):
    _inherit = "product.attribute.value"

    def with_saleor_skip(self):
        return self.with_context(saleor_sync_skip=True)

    def _saleor_dispatch(self):
        _dispatch(self, "product.attribute.value")


class ProductProduct(models.Model):
    _inherit = "product.product"

    def with_saleor_skip(self):
        return self.with_context(saleor_sync_skip=True)

    def _saleor_dispatch(self):
        _dispatch(self, "product.product")


class ProductTemplateAttributeValue(models.Model):
    _inherit = "product.template.attribute.value"

    def _saleor_dispatch_ptav(self):
        _dispatch_ptav(self)
