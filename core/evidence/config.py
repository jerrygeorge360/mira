"""Conservative rollout controls for source-aware evidence processing."""

from __future__ import annotations

import os


def document_enrichment_enabled(*, workspace_id: str, project_id: str | None = None) -> bool:
    """Allow enrichment only when enabled for this workspace or project."""
    return _enabled_for_scope("MIRA_DOCUMENT_ENRICHMENT", workspace_id, project_id)


def source_aware_retrieval_enabled(*, workspace_id: str, project_id: str | None = None) -> bool:
    """Allow generalized retrieval only when enabled for this scope."""
    return _enabled_for_scope("MIRA_SOURCE_AWARE_RETRIEVAL", workspace_id, project_id)


def _enabled_for_scope(prefix: str, workspace_id: str, project_id: str | None) -> bool:
    if os.environ.get(f"{prefix}_ENABLED", "false").strip().casefold() not in {"1", "true", "yes"}:
        return False
    workspaces = _ids(f"{prefix}_WORKSPACE_IDS")
    projects = _ids(f"{prefix}_PROJECT_IDS")
    return (
        workspace_id in workspaces
        or "*" in workspaces
        or (project_id is not None and (project_id in projects or "*" in projects))
    )


def _ids(name: str) -> frozenset[str]:
    return frozenset(
        value.strip() for value in os.environ.get(name, "").split(",") if value.strip()
    )
