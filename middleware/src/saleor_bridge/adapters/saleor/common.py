"""Shared helpers for Saleor GraphQL catalog mutations."""

from __future__ import annotations

from typing import Any

from saleor_bridge.saleor.client import SaleorClient


class SaleorError(RuntimeError):
    """Saleor returned top-level errors, or the mutation returned errors{}."""


def _is_slug_unique_error(errors: list[dict]) -> bool:
    for e in errors:
        if (e.get("field") == "slug") and (e.get("code") in ("UNIQUE", "ALREADY_EXISTS")):
            return True
        msg = (e.get("message") or "").lower()
        if "slug" in msg and ("already" in msg or "exist" in msg or "unique" in msg):
            return True
    return False


async def run_mutation(
    client: SaleorClient,
    query: str,
    variables: dict[str, Any],
    root: str,
) -> dict:
    """Execute a mutation, return the payload under `root`. Raises SaleorError on errors.

    `SaleorError` flags a slug collision via the `.slug_conflict` attribute for retry.
    """
    body = await client.execute(query, variables)
    if body.get("errors"):
        msg = "; ".join(e.get("message", "?") for e in body["errors"])
        raise SaleorError(f"{root}: top-level GraphQL error: {msg}")
    payload = (body.get("data") or {}).get(root) or {}
    errors = payload.get("errors") or []
    if errors:
        err = SaleorError(f"{root}: mutation errors: {errors}")
        err.slug_conflict = _is_slug_unique_error(errors)  # type: ignore[attr-defined]
        raise err
    return payload


async def query_data(client: SaleorClient, query: str, variables: dict | None = None) -> dict:
    body = await client.execute(query, variables or {})
    if body.get("errors"):
        msg = "; ".join(e.get("message", "?") for e in body["errors"])
        raise SaleorError(f"query error: {msg}")
    return body.get("data") or {}
