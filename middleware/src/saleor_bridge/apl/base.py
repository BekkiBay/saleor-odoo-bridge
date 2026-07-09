"""App Persistence Layer — interface для хранения {saleor_domain: app_token}.

Reference: https://docs.saleor.io/developer/extending/apps/developing-apps/app-sdk/apl
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class AuthData:
    saleor_api_url: str
    token: str
    app_id: str = ""
    domain: str = ""
    jwks: str = ""


class APL(ABC):
    """Abstract App Persistence Layer."""

    @abstractmethod
    async def get(self, saleor_api_url: str) -> AuthData | None: ...

    @abstractmethod
    async def set(self, auth: AuthData) -> None: ...

    @abstractmethod
    async def delete(self, saleor_api_url: str) -> None: ...

    @abstractmethod
    async def list_all(self) -> list[AuthData]: ...
