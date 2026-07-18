"""FastAPI application entrypoint for the MIRA product backend.

Ownership: Jerry.
Related issue: ISSUE-134.
Architecture area: API/server.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.access_logging import install_health_access_filter
from api.dependencies import configure_runtime_database, load_runtime_environment
from api.oauth import OAuthProtocolError, sync_first_party_oauth_clients
from api.rate_limit import rate_limit_middleware
from api.routes import (
    auth,
    chat,
    evaluation,
    health,
    memory,
    oauth,
    retrieval,
    sessions,
    worker,
    workspace,
)

DEFAULT_CORS_ORIGINS = (
    "http://localhost:8501",
    "http://localhost:3000",
    "http://localhost:5173",
)


def create_app() -> FastAPI:
    """Create and configure the MIRA FastAPI app."""
    load_runtime_environment()
    configure_runtime_database()
    sync_first_party_oauth_clients()
    install_health_access_filter()
    app = FastAPI(title="MIRA API", version="0.1.0")

    @app.exception_handler(OAuthProtocolError)
    def oauth_protocol_error(_request: Request, error: OAuthProtocolError) -> JSONResponse:
        return oauth.oauth_error_response(error)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.middleware("http")(rate_limit_middleware)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(oauth.router)
    app.include_router(workspace.router)
    app.include_router(chat.router)
    app.include_router(sessions.router)
    app.include_router(memory.router)
    app.include_router(retrieval.router)
    app.include_router(worker.router)
    app.include_router(evaluation.router)
    return app


def _cors_origins() -> list[str]:
    raw = os.environ.get("MIRA_API_CORS_ORIGINS")
    if raw:
        return [origin.strip() for origin in raw.split(",") if origin.strip()]
    return list(DEFAULT_CORS_ORIGINS)


app = create_app()
