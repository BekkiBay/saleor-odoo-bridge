"""respx router helper для order-мутаций Saleor (Phase 3.4 тесты). Не test_-модуль."""

from __future__ import annotations

import json

import httpx

_WAREHOUSE_ID = "V2FyZWhvdXNlOjE="


def make_saleor_router(order_node: dict, *, warehouse_id: str = _WAREHOUSE_ID, capture: list | None = None):
    """Вернуть side_effect для respx: отвечает на order query + lifecycle мутации."""

    def router(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        q = body["query"]
        if capture is not None:
            capture.append(body)
        oid = order_node["id"]
        if "warehouses(first:100)" in q:
            return httpx.Response(200, json={"data": {"warehouses": {"edges": [
                {"node": {"id": warehouse_id, "slug": "main", "name": "Main"}}]}}})
        if "orderConfirm(" in q:
            return httpx.Response(200, json={"data": {"orderConfirm": {
                "order": {"id": oid, "status": "UNFULFILLED"}, "errors": []}}})
        if "orderCancel(" in q:
            return httpx.Response(200, json={"data": {"orderCancel": {
                "order": {"id": oid, "status": "CANCELED"}, "errors": []}}})
        if "orderMarkAsPaid(" in q:
            return httpx.Response(200, json={"data": {"orderMarkAsPaid": {
                "order": {"id": oid, "isPaid": True}, "errors": []}}})
        if "orderFulfill(" in q:
            tracking = body["variables"]["input"].get("trackingNumber")
            return httpx.Response(200, json={"data": {"orderFulfill": {
                "fulfillments": [{"id": "RnVsZmlsbG1lbnQ6MQ==", "status": "FULFILLED",
                                  "trackingNumber": tracking}],
                "errors": []}}})
        if "updateMetadata(" in q:
            return httpx.Response(200, json={"data": {"updateMetadata": {
                "item": {"id": oid}, "errors": []}}})
        if "order(id:$id)" in q:
            return httpx.Response(200, json={"data": {"order": order_node}})
        raise AssertionError(f"unexpected Saleor query: {q[:70]}")

    return router


def order_node(
    oid: str = "T3JkZXI6MQ==",
    *,
    status: str = "UNCONFIRMED",
    is_paid: bool = False,
    payment: str = "NOT_CHARGED",
    lines: list | None = None,
) -> dict:
    return {
        "id": oid, "number": "1", "status": status, "isPaid": is_paid,
        "paymentStatus": payment, "fulfillments": [],
        "lines": lines if lines is not None else [],
    }


def order_line(line_id: str, sku: str, to_fulfill: int) -> dict:
    return {"id": line_id, "productSku": sku, "quantity": to_fulfill,
            "quantityToFulfill": to_fulfill, "variant": {"sku": sku}}
