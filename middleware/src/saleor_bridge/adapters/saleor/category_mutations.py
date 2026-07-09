"""Saleor Category мутации (create/update). Pure GraphQL; binding — в usecase."""

from __future__ import annotations

import structlog

from saleor_bridge.adapters.saleor.common import SaleorError, query_data, run_mutation
from saleor_bridge.adapters.saleor.slug import with_suffix
from saleor_bridge.saleor.client import SaleorClient

log = structlog.get_logger()

_CREATE = """
mutation($input: CategoryInput!, $parent: ID){
  categoryCreate(input:$input, parent:$parent){
    category{ id slug name }
    errors{ field message code }
  }
}
"""

_UPDATE = """
mutation($id: ID!, $input: CategoryInput!){
  categoryUpdate(id:$id, input:$input){
    category{ id slug name }
    errors{ field message code }
  }
}
"""

_MAX_SLUG_RETRY = 3


async def create_category(
    client: SaleorClient,
    *,
    name: str,
    slug: str,
    parent_saleor_id: str | None,
    suffix_seed: str,
) -> str:
    """Создать категорию; на slug-коллизии повторить с суффиксом suffix_seed."""
    attempt_slug = slug
    for attempt in range(_MAX_SLUG_RETRY):
        try:
            payload = await run_mutation(
                client, _CREATE,
                {"input": {"name": name, "slug": attempt_slug}, "parent": parent_saleor_id},
                "categoryCreate",
            )
            return payload["category"]["id"]
        except SaleorError as exc:
            if getattr(exc, "slug_conflict", False) and attempt < _MAX_SLUG_RETRY - 1:
                attempt_slug = with_suffix(slug, f"{suffix_seed}-{attempt + 1}" if attempt else suffix_seed)
                log.warning("category_slug_conflict_retry", slug=attempt_slug)
                continue
            raise
    raise SaleorError(f"category slug exhausted retries: {slug}")  # pragma: no cover


async def update_category(client: SaleorClient, saleor_id: str, *, name: str) -> str:
    payload = await run_mutation(
        client, _UPDATE,
        {"id": saleor_id, "input": {"name": name}},
        "categoryUpdate",
    )
    return payload["category"]["id"]


_PARENT = "query($id: ID!){ category(id:$id){ id parent{ id } } }"


async def fetch_parent_id(client: SaleorClient, saleor_id: str) -> str | None:
    """Текущий parent категории в Saleor (для detect parent-move divergence)."""
    data = await query_data(client, _PARENT, {"id": saleor_id})
    cat = data.get("category") or {}
    parent = cat.get("parent")
    return parent["id"] if parent else None
