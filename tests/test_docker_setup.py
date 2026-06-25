"""Verify ISSUE-054 local Docker development setup.

Ownership: MIRA contributors.
Related issue: ISSUE-054.
Architecture area: infra.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_exists_and_starts_streamlit() -> None:
    """The Docker image has a Streamlit app entry point."""
    dockerfile = PROJECT_ROOT / "Dockerfile"
    text = dockerfile.read_text(encoding="utf-8")

    assert dockerfile.is_file()
    assert "FROM python:3.11-slim" in text
    assert "streamlit" in text
    assert "ui/app.py" in text
    assert "EXPOSE 8501" in text


def test_compose_app_service_exposes_streamlit() -> None:
    """Docker Compose defines the optional Streamlit app service."""
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "app:" in compose
    assert "8501:8501" in compose
    assert "streamlit" in compose
    assert "ui/app.py" in compose
    assert "http://localhost:8501/_stcore/health" in compose


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
    assert "docker compose up app" in readme
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
