"""Document retrieval must obey the caller's source and Knowledge Base scope."""

from __future__ import annotations

import pytest

from core.retrieval import deep, quick, router


@pytest.fixture
def document_lookup(monkeypatch: pytest.MonkeyPatch) -> list[str | None]:
    calls: list[str | None] = []

    def fake_documents(
        _query: str,
        *,
        workspace_id: str,
        limit: int,
        knowledge_base_id: str | None = None,
    ) -> list[dict[str, object]]:
        assert workspace_id == "workspace_a"
        assert limit == 8
        calls.append(knowledge_base_id)
        # Simulate a stale or incorrect index result from another KB as well.
        return [
            {
                "chunk_id": f"chunk_{kb}",
                "knowledge_base_id": kb,
                "document_id": f"document_{kb}",
                "content": f"Private text from {kb}",
                "record": {"id": f"chunk_{kb}", "workspace_id": workspace_id},
            }
            for kb in ("kb_allowed", "kb_other")
        ]

    monkeypatch.setattr(quick, "retrieve_document_chunks", fake_documents)
    monkeypatch.setattr(quick, "_semantic_candidates", lambda *args, **kwargs: [])
    monkeypatch.setattr(quick, "_keyword_observation_candidates", lambda *args, **kwargs: [])
    monkeypatch.setattr(quick, "_atomic_fact_candidates", lambda *args, **kwargs: [])
    monkeypatch.setattr(quick, "_foresight_candidates", lambda *args, **kwargs: [])
    monkeypatch.setattr(router, "_matching_graph_node_ids", lambda *args: [])
    monkeypatch.setattr(deep, "_community_candidates", lambda *args, **kwargs: [])
    return calls


@pytest.mark.parametrize("mode", ["quick", "deep", "relational"])
def test_disabled_documents_never_start_document_search(
    document_lookup: list[str | None],
    mode: str,
) -> None:
    results = router.route_retrieval(
        "What is in the private document?",
        mode=mode,
        workspace_id="workspace_a",
        include_documents=False,
        allowed_knowledge_base_ids=("kb_allowed",),
    )
    assert results == []
    assert document_lookup == []


@pytest.mark.parametrize("mode", ["quick", "deep", "relational"])
def test_allowlist_limits_document_search_and_filters_stale_results(
    document_lookup: list[str | None],
    mode: str,
) -> None:
    results = router.route_retrieval(
        "What is in the private document?",
        mode=mode,
        workspace_id="workspace_a",
        allowed_knowledge_base_ids=("kb_allowed",),
    )
    assert document_lookup == ["kb_allowed"]
    assert [result["content"] for result in results] == ["Private text from kb_allowed"]


def test_empty_allowlist_skips_document_search(document_lookup: list[str | None]) -> None:
    assert (
        router.route_retrieval(
            "private document",
            mode="quick",
            workspace_id="workspace_a",
            allowed_knowledge_base_ids=(),
        )
        == []
    )
    assert document_lookup == []


def test_missing_session_attachment_fails_closed(
    document_lookup: list[str | None],
) -> None:
    results = router.route_retrieval(
        "private document",
        mode="quick",
        workspace_id="workspace_a",
    )
    assert results == []
    assert document_lookup == []


def test_session_default_uses_only_explicit_attachments(
    document_lookup: list[str | None], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        router,
        "list_session_knowledge_base_ids",
        lambda *_args, **_kwargs: ["kb_allowed"],
    )
    monkeypatch.setattr(
        router, "source_aware_retrieval_enabled_for_workspace", lambda **_kwargs: True
    )
    monkeypatch.setattr(quick, "workspace_id_for_session", lambda _session_id: "workspace_a")
    results = router.route_retrieval(
        "private document",
        mode="quick",
        session_id="session_a",
        workspace_id="workspace_a",
    )
    assert document_lookup == ["kb_allowed"]
    assert [result["knowledge_base_id"] for result in results] == ["kb_allowed"]


def test_source_aware_rollout_flag_disables_session_document_retrieval(
    document_lookup: list[str | None], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        router, "list_session_knowledge_base_ids", lambda *_args, **_kwargs: ["kb_allowed"]
    )
    monkeypatch.setattr(
        router, "source_aware_retrieval_enabled_for_workspace", lambda **_kwargs: False
    )
    monkeypatch.setattr(quick, "workspace_id_for_session", lambda _session_id: "workspace_a")
    results = router.route_retrieval(
        "private document",
        mode="quick",
        session_id="session_a",
        workspace_id="workspace_a",
    )
    assert results == []
    assert document_lookup == []
