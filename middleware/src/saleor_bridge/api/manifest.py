"""Saleor App Manifest endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from saleor_bridge.config import Settings, get_settings
from saleor_bridge.saleor.manifest_schema import AppManifest

router = APIRouter(tags=["manifest"])


@router.get("/manifest")
async def manifest(settings: Settings = Depends(get_settings)) -> dict:
    """Return the App Manifest with the public URL substituted.

    Saleor fetches this endpoint during the `appInstall` mutation.
    Reference: https://docs.saleor.io/developer/extending/apps/architecture/manifest
    """
    m = AppManifest.build(public_url=settings.middleware_public_url, settings=settings)
    return m.model_dump(exclude_none=True)
