"""Small in-process API rate limiter for the local/product backend."""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.responses import JSONResponse

_WINDOWS: dict[str, deque[float]] = defaultdict(deque)


async def rate_limit_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Limit requests by client address.

    This is intentionally simple and dependency-free. It is enough for the
    single-process Docker/local deployment; production can replace it with a
    shared Redis or edge limiter.
    """
    if not _enabled() or request.url.path == "/health":
        return await call_next(request)

    key = _client_key(request)
    limit = _limit_for_path(request.url.path)
    window_s = _window_seconds()
    now = time.monotonic()
    bucket = _WINDOWS[key]
    while bucket and now - bucket[0] >= window_s:
        bucket.popleft()
    if len(bucket) >= limit:
        retry_after = max(1, int(window_s - (now - bucket[0]))) if bucket else int(window_s)
        return JSONResponse(
            {"detail": "rate limit exceeded; try again shortly"},
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )
    bucket.append(now)
    return await call_next(request)


def reset_rate_limiter() -> None:
    """Clear in-memory rate-limit state for tests."""
    _WINDOWS.clear()


def _enabled() -> bool:
    return os.environ.get("MIRA_RATE_LIMIT_ENABLED", "true").strip().lower() not in {
        "0",
        "false",
        "no",
    }


def _limit_for_path(path: str) -> int:
    if path == "/chat":
        return _positive_int_env("MIRA_CHAT_RATE_LIMIT_REQUESTS", 30)
    return _positive_int_env("MIRA_RATE_LIMIT_REQUESTS", 120)


def _window_seconds() -> int:
    return _positive_int_env("MIRA_RATE_LIMIT_WINDOW_S", 60)


def _positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    host = forwarded.split(",", maxsplit=1)[0].strip() if forwarded else None
    if not host and request.client is not None:
        host = request.client.host
    return f"{host or 'unknown'}:{request.url.path}"
