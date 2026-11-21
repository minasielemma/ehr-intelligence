"""Core security utilities and authentication scaffolding.

Provides active API Key authentication and authorization verification dependencies.
"""

from typing import List, Optional
from fastapi import Depends, Security, status
from fastapi.security import APIKeyHeader

from app.api.dependencies import get_current_settings
from app.core.config import Settings
from app.core.exceptions import AppException

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


class SecurityContext:
    """Security context holding authenticated user/caller identity and roles."""

    def __init__(
        self,
        user_id: Optional[str] = None,
        roles: Optional[List[str]] = None,
        is_authenticated: bool = False,
    ) -> None:
        self.user_id = user_id
        self.roles = roles or []
        self.is_authenticated = is_authenticated


async def verify_api_key(
    api_key: Optional[str] = Security(api_key_header),
    settings: Settings = Depends(get_current_settings),
) -> SecurityContext:
    """Verify incoming X-API-Key header against configured API keys.

    If REQUIRE_AUTH is False, allows pass-through without an API key for development/testing.
    If REQUIRE_AUTH is True or if an invalid API key is explicitly supplied, rejects with HTTP 401.
    """
    if not settings.REQUIRE_AUTH:
        # Development / Testing pass-through when auth is not strictly enforced
        if not api_key:
            return SecurityContext(user_id="dev-user", roles=["admin"], is_authenticated=True)

    if not api_key:
        raise AppException(
            message="Missing required API Key header 'X-API-Key'.",
            status_code=status.HTTP_401_UNAUTHORIZED,
            error_code="UNAUTHORIZED",
            details={"header": settings.API_KEY_HEADER_NAME},
        )

    if api_key not in settings.API_KEYS:
        raise AppException(
            message="Invalid or revoked API Key.",
            status_code=status.HTTP_401_UNAUTHORIZED,
            error_code="UNAUTHORIZED",
            details={"header": settings.API_KEY_HEADER_NAME},
        )

    return SecurityContext(user_id="api-key-caller", roles=["ingestion"], is_authenticated=True)
