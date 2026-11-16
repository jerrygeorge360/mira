"""Rollout gates keep new evidence paths disabled without explicit scope selection."""

from __future__ import annotations

from core.evidence.config import document_enrichment_enabled, source_aware_retrieval_enabled


def test_document_enrichment_requires_feature_and_selected_workspace(monkeypatch) -> None:
    monkeypatch.setenv("MIRA_DOCUMENT_ENRICHMENT_WORKSPACE_IDS", "workspace-a")
    assert not document_enrichment_enabled(workspace_id="workspace-a")

    monkeypatch.setenv("MIRA_DOCUMENT_ENRICHMENT_ENABLED", "true")
    assert document_enrichment_enabled(workspace_id="workspace-a")
    assert not document_enrichment_enabled(workspace_id="workspace-b")


def test_source_aware_retrieval_can_select_one_project(monkeypatch) -> None:
    monkeypatch.setenv("MIRA_SOURCE_AWARE_RETRIEVAL_ENABLED", "true")
    monkeypatch.setenv("MIRA_SOURCE_AWARE_RETRIEVAL_PROJECT_IDS", "prj-allowed")
    assert source_aware_retrieval_enabled(workspace_id="workspace-a", project_id="prj-allowed")
    assert not source_aware_retrieval_enabled(workspace_id="workspace-a", project_id="prj-other")
    assert not source_aware_retrieval_enabled(workspace_id="workspace-a")
