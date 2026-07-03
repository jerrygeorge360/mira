"""Tests for the MIRA FastAPI health/CORS boundary."""

from __future__ import annotations

from fastapi.middleware.cors import CORSMiddleware

from api.main import create_app
from api.routes.health import health


def test_health_endpoint_returns_ok() -> None:
    assert health() == {"status": "ok", "service": "mira-api"}


def test_cors_allows_local_frontend_origin() -> None:
    app = create_app()
    cors = next(
        middleware for middleware in app.user_middleware if middleware.cls is CORSMiddleware
    )
    assert "http://localhost:5173" in cors.kwargs["allow_origins"]
