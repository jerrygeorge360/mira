"""API authentication and rate-limit boundary tests."""

from __future__ import annotations

import pytest
from fastapi import HTTPException, Request, Response

from api.auth import require_authenticated_workspace
from api.rate_limit import rate_limit_middleware, reset_rate_limiter


def test_product_auth_dependency_rejects_missing_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIRA_AUTH_MODE", "github")
    request = Request(
        {"type": "http", "method": "GET", "path": "/evaluation/summary", "headers": []}
    )

    with pytest.raises(HTTPException) as exc_info:
        require_authenticated_workspace(request)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_rate_limiter_blocks_repeated_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_rate_limiter()
    monkeypatch.setenv("MIRA_RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("MIRA_RATE_LIMIT_REQUESTS", "2")
    monkeypatch.setenv("MIRA_RATE_LIMIT_WINDOW_S", "60")
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/auth/me",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    async def call_next(_: Request) -> Response:
        return Response(status_code=200)

    assert (await rate_limit_middleware(request, call_next)).status_code == 200
    assert (await rate_limit_middleware(request, call_next)).status_code == 200
    response = await rate_limit_middleware(request, call_next)

    assert response.status_code == 429
