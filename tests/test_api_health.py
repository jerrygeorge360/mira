"""Tests for the MIRA FastAPI health/CORS boundary."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.middleware.cors import CORSMiddleware

from api.access_logging import SuccessfulHealthCheckFilter
from api.dependencies import load_runtime_environment
from api.main import create_app
from api.routes.health import health


def _access_record(path: str, status_code: int) -> logging.LogRecord:
    return logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1234", "GET", path, "1.1", status_code),
        None,
    )


def test_successful_health_access_logs_are_suppressed() -> None:
    access_filter = SuccessfulHealthCheckFilter()

    assert access_filter.filter(_access_record("/health", 200)) is False
    assert access_filter.filter(_access_record("/health", 503)) is True
    assert access_filter.filter(_access_record("/sessions", 200)) is True


def test_health_endpoint_returns_ok() -> None:
    assert health() == {"status": "ok", "service": "mira-api"}


def test_cors_allows_local_frontend_origin() -> None:
    app = create_app()
    cors = next(
        middleware
        for middleware in cast(list[Any], app.user_middleware)
        if middleware.cls is CORSMiddleware
    )
    allow_origins = cast(list[str], cors.kwargs["allow_origins"])
    assert "http://localhost:5173" in allow_origins


def test_api_runtime_loads_dotenv_without_overriding_shell_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MIRA_TEST_DOTENV_VALUE", raising=False)
    monkeypatch.setenv("MIRA_TEST_SHELL_VALUE", "from-shell")
    (tmp_path / ".env").write_text(
        "MIRA_TEST_DOTENV_VALUE=from-dotenv\nMIRA_TEST_SHELL_VALUE=from-dotenv\n",
        encoding="utf-8",
    )

    loaded = load_runtime_environment()

    assert loaded is True
    assert os.environ["MIRA_TEST_DOTENV_VALUE"] == "from-dotenv"
    assert os.environ["MIRA_TEST_SHELL_VALUE"] == "from-shell"
