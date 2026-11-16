"""Usage metering middleware for authenticated public `/v1` requests."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response

from core.platform.service import PlatformAPIKey, record_usage_event

LOGGER = logging.getLogger(__name__)


async def public_api_metering_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    if not request.url.path.startswith("/v1/"):
        return await call_next(request)
    started = time.perf_counter()
    response = await call_next(request)
    api_key = getattr(request.state, "platform_api_key", None)
    if not isinstance(api_key, PlatformAPIKey):
        return response
    rate_limit = getattr(request.state, "rate_limit", None)
    if isinstance(rate_limit, tuple) and len(rate_limit) == 3:
        limit, remaining, reset_at = rate_limit
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, remaining - 1))
        response.headers["X-RateLimit-Reset"] = str(reset_at)
    content_length = request.headers.get("content-length", "0")
    try:
        bytes_received = max(0, int(content_length))
    except ValueError:
        bytes_received = 0
    operation = str(getattr(request.state, "platform_operation", "api.request"))
    characters = int(getattr(request.state, "platform_characters", 0))
    namespace = getattr(request.state, "platform_namespace", None)
    try:
        uploaded_bytes = int(getattr(request.state, "platform_bytes_ingested", 0))
        if operation == "document.upload" and uploaded_bytes == 0:
            # Fall back for an unusual upload handler that did not provide a file size.
            uploaded_bytes = bytes_received
        if response.status_code < 200 or response.status_code >= 300:
            uploaded_bytes = 0
        record_usage_event(
            api_key,
            operation=operation,
            status_code=response.status_code,
            latency_ms=int((time.perf_counter() - started) * 1000),
            namespace=str(namespace) if namespace else None,
            bytes_ingested=uploaded_bytes,
            characters_processed=characters,
        )
    except Exception:  # noqa: BLE001 - metering must not replace the API response
        LOGGER.exception("public API usage event could not be recorded")
    return response
