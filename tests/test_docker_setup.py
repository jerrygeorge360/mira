"""Verify ISSUE-054 local Docker development setup.

Ownership: MIRA contributors.
Related issue: ISSUE-054.
Architecture area: infra.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_exists_and_starts_api() -> None:
    """The Docker image has a FastAPI entry point."""
    dockerfile = PROJECT_ROOT / "Dockerfile"
    text = dockerfile.read_text(encoding="utf-8")

    assert dockerfile.is_file()
    assert "FROM python:3.11-slim" in text
    assert "uvicorn" in text
    assert "api.main:app" in text
    assert "EXPOSE 8000" in text


def test_compose_services_expose_api_worker_mcp_and_frontend() -> None:
    """Docker Compose defines the product API, worker, MCP, and frontend services."""
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "api:" in compose
    assert "worker:" in compose
    assert "mcp:" in compose
    assert "frontend:" in compose
    assert "${API_PORT:-8000}:8000" in compose
    assert "${FRONTEND_PORT:-5173}:5173" in compose
    assert "http://localhost:8000/health" in compose
    assert "integrations.mcp.service:app" in compose


def test_production_proxy_exposes_mcp_oauth_discovery() -> None:
    """The public proxy routes MCP and both OAuth discovery documents."""
    nginx = (PROJECT_ROOT / "nginx/default.conf").read_text(encoding="utf-8")

    assert "location = /mcp" in nginx
    assert "location ^~ /oauth/" in nginx
    assert "location = /.well-known/oauth-authorization-server" in nginx
    assert "location = /.well-known/oauth-protected-resource/mcp" in nginx


def test_compose_mounts_sqlite_and_chroma_paths() -> None:
    """SQLite and Chroma paths are mounted so demo data persists."""
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "MIRA_DB_PATH: /data/sqlite/mira.db" in compose
    assert "CHROMA_DB_PATH: /data/chroma" in compose
    assert "./.docker-data/sqlite:/data/sqlite" in compose
    assert "./.docker-data/chroma:/data/chroma" in compose


def test_environment_documentation_mentions_docker_paths() -> None:
    """The example environment documents local and Docker data paths."""
    env_example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")

    assert "MIRA_DB_PATH=./mira.db" in env_example
    assert "CHROMA_DB_PATH=./chroma_db" in env_example
    assert "MIRA_DB_PATH=/data/sqlite/mira.db" in env_example
    assert "CHROMA_DB_PATH=/data/chroma" in env_example


def test_readme_includes_docker_instructions() -> None:
    """The README tells a clean clone how to run locally with Docker."""
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

    assert "Docker local development" in readme
    assert "docker compose build" in readme
    assert "docker compose up api worker frontend" in readme
    assert ".docker-data/sqlite/mira.db" in readme
    assert ".docker-data/chroma" in readme


def test_streamlit_dependency_is_available_to_container() -> None:
    """The app image installs Streamlit through production requirements."""
    requirements = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert "streamlit" in requirements


def test_dockerignore_excludes_local_state_and_secrets() -> None:
    """The Docker build context excludes local data, virtualenvs, and secrets."""
    dockerignore = (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert ".env" in dockerignore
    assert ".venv" in dockerignore
    assert ".git" in dockerignore
    assert ".docker-data" in dockerignore
    assert "*.sqlite3" in dockerignore
