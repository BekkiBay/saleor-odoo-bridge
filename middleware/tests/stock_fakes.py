"""Minimal FakeOdoo for stock-sync unit/integration tests.

Covers the methods exercised by the stock adapters + BindingRepository:
read / search_read / search / create / write. Without a test_ prefix → pytest
doesn't collect it as a test module.
"""

from __future__ import annotations


def domain_val(domain: list, field: str):
    """Extract the value from a ('field', '=', value) domain clause."""
    for clause in domain:
        if isinstance(clause, (list, tuple)) and len(clause) == 3 and clause[0] == field:
            return clause[2]
    return None


class FakeOdoo:
    def __init__(
        self,
        *,
        variants: dict | None = None,
        quants: list | None = None,
        warehouses: list | None = None,
        bindings: dict | None = None,
        sale_orders: dict | None = None,
        pickings: dict | None = None,
        move_lines: dict | None = None,
        attributes: dict | None = None,
        attribute_values: dict | None = None,
        ptavs: dict | None = None,
        products: dict | None = None,
        taxes: dict | None = None,
    ) -> None:
        self.variants = variants or {}        # pp_id -> {default_code, product_tmpl_id, lst_price, ...}
        self.quants = quants or []            # [{quantity, product_id}]
        self.warehouses = warehouses or []    # [{id, name, code}]
        self.bindings = bindings or {}        # (model_name, odoo_id) -> saleor_id
        self.sale_orders = sale_orders or {}  # so_id -> {state, name}
        self.pickings = pickings or {}        # pick_id -> {state, sale_id, carrier_tracking_ref, move_line_ids}
        self.move_lines = move_lines or {}    # ml_id -> {product_id, quantity}
        self.attributes = attributes or {}    # attr_id -> {name, create_variant, value_ids}
        self.attribute_values = attribute_values or {}  # val_id -> {name, html_color, attribute_id}
        self.ptavs = ptavs or {}              # ptav_id -> {attribute_id, product_attribute_value_id}
        self.products = products or {}   # default_code -> product.product id
        self.taxes = taxes or {}         # rate(float, percent) -> account.tax id
        self.writes: list[tuple] = []
        self.creates: list[tuple] = []
        self.calls: list[tuple] = []          # (model, method, kwargs) — for the skip-guard test

    async def read(self, model: str, ids: list[int], fields: list[str]) -> list[dict]:
        if model == "product.product":
            return [{"id": i, **self.variants[i]} for i in ids if i in self.variants]
        if model == "sale.order":
            return [{"id": i, **self.sale_orders[i]} for i in ids if i in self.sale_orders]
        if model == "stock.picking":
            return [{"id": i, **self.pickings[i]} for i in ids if i in self.pickings]
        if model == "stock.move.line":
            return [{"id": i, **self.move_lines[i]} for i in ids if i in self.move_lines]
        if model == "product.attribute":
            return [{"id": i, **self.attributes[i]} for i in ids if i in self.attributes]
        if model == "product.attribute.value":
            return [{"id": i, **self.attribute_values[i]} for i in ids if i in self.attribute_values]
        if model == "product.template.attribute.value":
            return [{"id": i, **self.ptavs[i]} for i in ids if i in self.ptavs]
        raise AssertionError(f"FakeOdoo.read unexpected model {model}")

    async def call(self, model: str, method: str, **kwargs):
        """Record the call (for verifying the skip-guard context). Returns a sensible default."""
        self.calls.append((model, method, kwargs))
        if method == "create":
            return [1]
        return None

    async def search_read(
        self, model: str, domain: list, fields: list[str], limit: int | None = None
    ) -> list[dict]:
        if model == "saleor.binding":
            mn = domain_val(domain, "model_name")
            oid = domain_val(domain, "odoo_id")
            sid = self.bindings.get((mn, oid))
            return [{"saleor_id": sid, "odoo_id": oid}] if sid else []
        if model == "stock.warehouse":
            rows = self.warehouses
            return rows[:limit] if limit else rows
        if model == "stock.quant":
            return [{"quantity": q["quantity"]} for q in self.quants]
        if model == "res.currency":
            return []
        if model == "product.product":
            code = domain_val(domain, "default_code")
            pid = self.products.get(code)
            return [{"id": pid}] if pid else []
        if model == "account.tax":
            amount = domain_val(domain, "amount")
            tid = self.taxes.get(float(amount)) if amount is not None else None
            return [{"id": tid}] if tid else []
        if model == "sale.order":
            return [{"id": next(iter(self.sale_orders))}] if self.sale_orders else []
        raise AssertionError(f"FakeOdoo.search_read unexpected model {model}")

    async def search(self, model: str, domain: list, limit: int | None = None) -> list[int]:
        if model == "saleor.binding":
            mn = domain_val(domain, "model_name")
            oid = domain_val(domain, "odoo_id")
            return [1] if (mn, oid) in self.bindings else []
        if model == "product.product":
            tmpl = domain_val(domain, "product_tmpl_id")
            ids = []
            for pid, v in self.variants.items():
                vt = v.get("product_tmpl_id")
                vt_id = vt[0] if isinstance(vt, (list, tuple)) else vt
                if tmpl is not None and vt_id != tmpl:
                    continue
                if v.get("active", True) is False:
                    continue
                ids.append(pid)
            return ids
        raise AssertionError(f"FakeOdoo.search unexpected model {model}")

    async def create(self, model: str, vals: dict) -> int:
        self.creates.append((model, vals))
        if model == "saleor.binding":
            self.bindings[(vals["model_name"], vals["odoo_id"])] = vals["saleor_id"]
        return 1

    async def write(self, model: str, ids: list[int], vals: dict) -> bool:
        self.writes.append((model, ids, vals))
        return True
