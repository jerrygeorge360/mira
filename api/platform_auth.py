"""Bearer API-key authentication and scope checks for the public developer API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from core.platform.service import (
    PlatformAPIKey,
    authenticate_api_key,
    check_rate_limit,
)


def require_api_key(request: Request) -> PlatformAPIKey:
    authorization = request.headers.get("Authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.casefold() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="valid API key required")
    api_key = authenticate_api_key(token.strip())
    if api_key is None:
        raise HTTPException(status_code=401, detail="valid API key required")
    request.state.platform_api_key = api_key
    limit, remaining, reset_at = check_rate_limit(api_key)
    request.state.rate_limit = (limit, remaining, reset_at)
    if remaining <= 0:
        raise HTTPException(
            status_code=429,
            detail={"error": "rate_limit_exceeded", "message": "API key rate limit exceeded."},
            headers={"Retry-After": str(max(1, reset_at - int(datetime.now(UTC).timestamp())))},
        )
    return api_key


def require_scope(api_key: PlatformAPIKey, scope: str) -> None:
    if scope not in api_key.scopes:
        raise HTTPException(
            status_code=403,
            detail={"error": "insufficient_scope", "message": f"This key requires {scope}."},
        )


APIKeyAuth = Annotated[PlatformAPIKey, Depends(require_api_key)]
