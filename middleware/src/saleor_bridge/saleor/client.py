"""Saleor GraphQL client — a thin wrapper around httpx.

This is the core GraphQL client used for all Saleor queries and mutations,
including multipart file uploads.
"""

from __future__ import annotations

import json

import httpx
import structlog

log = structlog.get_logger()


class SaleorClient:
    def __init__(self, api_url: str, app_token: str = "") -> None:
        self.api_url = api_url
        self.app_token = app_token

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.app_token:
            headers["Authorization"] = f"Bearer {self.app_token}"
        return headers

    async def execute(self, query: str, variables: dict | None = None) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                self.api_url,
                headers=self._headers(),
                json={"query": query, "variables": variables or {}},
            )
            r.raise_for_status()
            body = r.json()
            if "errors" in body:
                log.warning("saleor_graphql_errors", errors=body["errors"], query=query[:120])
            return body

    async def execute_upload(
        self,
        query: str,
        variables: dict,
        *,
        file_field_path: str,
        filename: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> dict:
        """GraphQL multipart request (spec: jaydenseric/graphql-multipart-request-spec).

        Used for productMediaCreate (Upload scalar). The `Upload` variable must be
        null in `variables`; the file is mapped to it via `file_field_path`
        (e.g. "variables.image").
        """
        operations = json.dumps({"query": query, "variables": variables})
        file_map = json.dumps({"0": [file_field_path]})
        headers: dict[str, str] = {}
        if self.app_token:
            headers["Authorization"] = f"Bearer {self.app_token}"
        # No Content-Type header — httpx sets the multipart boundary itself.
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                self.api_url,
                headers=headers,
                files={
                    "operations": (None, operations, "application/json"),
                    "map": (None, file_map, "application/json"),
                    "0": (filename, content, content_type),
                },
            )
            r.raise_for_status()
            body = r.json()
            if "errors" in body:
                log.warning("saleor_graphql_errors", errors=body["errors"], query=query[:120])
            return body

    async def shop_version(self) -> str | None:
        """Public field schemaVersion — does not require auth."""
        body = await self.execute("query { shop { schemaVersion } }")
        return body.get("data", {}).get("shop", {}).get("schemaVersion")
