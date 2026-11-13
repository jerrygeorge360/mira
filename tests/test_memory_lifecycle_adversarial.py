"""Deterministic adversarial checks for memory lifecycle boundaries.

These tests intentionally use public repository, retrieval, agent, tier, and worker
seams. They do not require an LLM, network access, or a lifecycle implementation
that is broader than the currently exposed contracts.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from core import agent
from core.context.merger import merge_context_sources
from core.db import chroma
from core.db.repositories import (
    WorkspaceContext,
    bind_workspace,
    configure_database,
    create_atomic_fact,
    create_community_summary,
    create_reflection,
    create_session,
    create_workspace,
    get_answer_trace,
    list_session_items_by_status,
    repository_connection,
    save_observation,
)
from core.db.schema import LEGACY_WORKSPACE_ID
from core.llm.embeddings import embed_text
from core.memory.lifecycle import (
    ensure_memory_state,
    forget_memory,
    get_memory_state,
    list_memory_states,
    record_feedback,
    run_memory_sleep,
)
from core.memory.tiers import (
    evaluate_promotion_candidate,
    list_hot_memory_for_context,
    promote_to_hot_memory,
)
from core.retrieval.deep import retrieve_deep
from core.retrieval.quick import retrieve_quick
from core.session.working_set import (
    expire_session_item,
    list_active_session_items,
    upsert_session_item,
)


@pytest.fixture
def isolated_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Give every scenario fresh SQLite and vector state."""
    database_path = tmp_path / "mira.sqlite3"
    monkeypatch.setenv("EMBEDDING_MODE", "deterministic")

    def no_chromadb(_module_name: str) -> object:
        raise ModuleNotFoundError("adversarial tests use the offline vector fallback")

    monkeypatch.setattr(chroma.importlib, "import_module", no_chromadb)
    configure_database(database_path)
    chroma.reset_vector_store()
    yield database_path
    chroma.reset_vector_store()


def _correction(session_id: str, content: str) -> str:
    observation_id = save_observation(session_id, "user", content)
    return upsert_session_item(
        session_id,
        {
            "type": "correction",
            "content": content,
            "scope": "project",
            "status": "confirmed",
            "priority": 0.95,
            "explicitness_label": "direct_correction",
            "evidence_span": content,
            "source_observations": [observation_id],
            "supersedes": [],
        },
    )


def test_stale_but_relevant_records_are_excluded_from_retrieval(
    isolated_memory: Path,
) -> None:
    """A matching superseded fact and stale reflection cannot re-enter answer context."""
    del isolated_memory
    session_id = create_session("jerry")

    old_observation = save_observation(session_id, "user", "The old database is MongoDB.")
    old_fact = create_atomic_fact(
        {
            "subject": "workspace",
            "predicate": "database",
            "object": "MongoDB",
            "confidence": 0.99,
            "source_observation_id": old_observation,
        }
    )
    current_observation = save_observation(
        session_id, "user", "The current database is PostgreSQL."
    )
    current_fact = create_atomic_fact(
        {
            "subject": "workspace",
            "predicate": "database",
            "object": "PostgreSQL",
            "confidence": 0.99,
            "source_observation_id": current_observation,
        }
    )
    with repository_connection() as connection:
        connection.execute(
            "UPDATE atomic_facts SET status = ? WHERE id = ?",
            ("superseded", old_fact),
        )

    quick = retrieve_quick("workspace database", session_id, limit=10)
    quick_fact_ids = {
        str(item["source_id"]) for item in quick if item.get("source") == "atomic_facts"
    }
    assert current_fact in quick_fact_ids
    assert old_fact not in quick_fact_ids

    stale_reflection = create_reflection(
        {
            "reflection_type": "self_knowledge",
            "content": "The stale database policy says MongoDB is current.",
            "confidence": 0.99,
            "status": "stale",
        }
    )
    chroma.add_embedding(
        "reflections",
        "reflections",
        stale_reflection,
        embed_text("The stale database policy says MongoDB is current."),
        workspace_id=LEGACY_WORKSPACE_ID,
    )
    create_community_summary(
        {
            "community_id": "database-policy",
            "title": "Database policy",
            "summary": "Memory retrieval and database policy are cached here.",
            "member_nodes_json": [],
        }
    )

    deep = retrieve_deep("database policy", session_id, limit=10)
    assert any(item.get("source") == "community_summary" for item in deep)
    assert all(item.get("source_id") != stale_reflection for item in deep)


def test_expired_memory_is_hidden_but_retained_for_audit(isolated_memory: Path) -> None:
    """Forgetting removes prompt visibility while preserving source and promotion history."""
    del isolated_memory
    session_id = create_session("jerry")
    item_id = _correction(session_id, "Use PostgreSQL for the project database.")
    hot_id = promote_to_hot_memory(evaluate_promotion_candidate("session_working_set", item_id))
    source_observation_id = str(list_active_session_items(session_id)[0]["source_observations"][0])
    lifecycle_state = ensure_memory_state(
        "observations", source_observation_id, LEGACY_WORKSPACE_ID
    )
    reinforced = record_feedback(
        "observations",
        source_observation_id,
        LEGACY_WORKSPACE_ID,
        answer_correct=True,
        verified=True,
        evidence={"test": "reinforcement"},
    )
    assert reinforced["successful_uses"] == 1
    assert reinforced["verification_count"] == 1
    assert reinforced["retention_score"] > lifecycle_state["retention_score"]

    forgotten = forget_memory(
        "observations",
        source_observation_id,
        LEGACY_WORKSPACE_ID,
        reason="adversarial forgetting",
        now="2026-01-03T00:00:00+00:00",
    )
    assert forgotten["lifecycle_status"] == "forgotten"
    assert list_memory_states(LEGACY_WORKSPACE_ID, include_inactive=False) == []
    assert (
        get_memory_state("observations", source_observation_id, LEGACY_WORKSPACE_ID)[
            "lifecycle_status"
        ]
        == "forgotten"
    )

    expire_session_item(session_id, item_id, "superseded by a newer database decision")

    assert list_active_session_items(session_id) == []
    assert list_session_items_by_status(session_id, "expired")[0]["id"] == item_id
    assert list_hot_memory_for_context(session_id, "project database", limit=10) == []
    assert all(
        item.get("source_id") != source_observation_id
        for item in retrieve_quick("project database", session_id, limit=10)
    )

    with repository_connection() as connection:
        source = connection.execute(
            "SELECT status FROM session_working_set WHERE id = ?",
            (item_id,),
        ).fetchone()
        hot = connection.execute(
            "SELECT status, source_record_id FROM working_memory WHERE id = ?",
            (hot_id,),
        ).fetchone()
    assert source is not None and source["status"] == "expired"
    assert hot is not None and hot["status"] == "active"
    assert hot["source_record_id"] == item_id


def test_retrieval_cannot_cross_workspace_boundaries(isolated_memory: Path) -> None:
    """Workspace A retrieval excludes equally relevant observations and facts from B."""
    del isolated_memory
    workspace_a = create_workspace("A", "adversarial-a", "development")
    workspace_b = create_workspace("B", "adversarial-b", "development")
    repo_a = bind_workspace(WorkspaceContext(workspace_a))
    repo_b = bind_workspace(WorkspaceContext(workspace_b))
    session_a = repo_a.create_session("user-a")
    session_b = repo_b.create_session("user-b")

    observation_a = repo_a.save_observation(session_a, "user", "Workspace database is PostgreSQL.")
    observation_b = repo_b.save_observation(session_b, "user", "Workspace database is MongoDB.")
    fact_a = create_atomic_fact(
        {
            "subject": "workspace",
            "predicate": "database",
            "object": "PostgreSQL",
            "confidence": 1.0,
            "source_observation_id": observation_a,
        }
    )
    fact_b = create_atomic_fact(
        {
            "subject": "workspace",
            "predicate": "database",
            "object": "MongoDB",
            "confidence": 1.0,
            "source_observation_id": observation_b,
        }
    )

    results = retrieve_quick("workspace database", session_a, limit=20)
    result_ids = {str(item.get("source_id")) for item in results if item.get("source_id")}
    result_content = {str(item.get("content")) for item in results}
    assert fact_a in result_ids
    assert fact_b not in result_ids
    assert all("MongoDB" not in content for content in result_content)


def test_verification_precedes_generation_and_trace_links_evidence(
    isolated_memory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The agent exposes retrieval, verification, generation order and persisted provenance."""
    del isolated_memory
    session_id = create_session("jerry")
    fact_observation_id = save_observation(
        session_id, "user", "The workspace database is PostgreSQL."
    )
    verification_fact_id = create_atomic_fact(
        {
            "subject": "workspace",
            "predicate": "database",
            "object": "PostgreSQL",
            "confidence": 1.0,
            "source_observation_id": fact_observation_id,
        }
    )
    expected_session_id = session_id
    retrieved_evidence = retrieve_quick(
        "workspace database", session_id, limit=agent.RETRIEVAL_LIMIT
    )
    assert any(item.get("source_id") == verification_fact_id for item in retrieved_evidence)
    stages: list[str] = []

    def route(_query: str, _session_id: str, *, strategy: str) -> dict[str, object]:
        assert strategy == "hybrid"
        return {
            "mode": "quick",
            "route": "memory",
            "reason": "test route",
            "intent": "personal_memory",
            "confidence": 1.0,
            "used_memory": True,
            "needs_sufficiency_check": True,
        }

    def retrieve(
        _query: str,
        *,
        mode: str,
        limit: int,
        session_id: str,
    ) -> list[dict[str, object]]:
        assert mode == "quick"
        assert limit == agent.RETRIEVAL_LIMIT
        assert session_id == expected_session_id
        stages.append("retrieval_call")
        return [dict(item) for item in retrieved_evidence]

    def qwen(_messages: list[dict[str, str]], schema_name: str) -> dict[str, object]:
        assert schema_name == "answer_generation"
        stages.append("generation_call")
        return {"json": {"answer": "PostgreSQL"}}

    monkeypatch.setattr(agent, "route_retrieval", route)
    monkeypatch.setattr(agent, "retrieve_by_mode", retrieve)
    monkeypatch.setattr(agent, "call_qwen_json", qwen)

    response = agent.handle_user_message(
        session_id,
        "Which database do I use?",
        progress_callback=lambda event: stages.append(str(event["stage"])),
    )

    assert stages.index("retrieval_call") < stages.index("verification")
    assert stages.index("verification") < stages.index("generation_call")
    assert response["retrieval_trace"]["needs_sufficiency_check"] is True

    trace = get_answer_trace(str(response["trace_id"]))
    assert trace is not None
    assert trace["retrieved_fact_ids_json"] == [verification_fact_id]
    assert trace["retrieval_log_id"]
    assert trace["prompt_log_id"]
    sufficiency = trace["sufficiency_json"]
    assert isinstance(sufficiency, dict)
    assert sufficiency["verification"]["verified"] is True
    assert sufficiency["verification"]["sufficient"] is True

    with repository_connection() as connection:
        retrieval_log = connection.execute(
            "SELECT retrieved_records_json FROM retrieval_logs WHERE id = ?",
            (trace["retrieval_log_id"],),
        ).fetchone()
    assert retrieval_log is not None
    retrieved_log_records = json.loads(retrieval_log["retrieved_records_json"])
    assert retrieved_log_records[0]["id"] == verification_fact_id
    assert retrieved_log_records[0]["prompt_eligible"] is True


def test_duplicate_consolidation_is_idempotent_and_keeps_provenance(
    isolated_memory: Path,
) -> None:
    """Duplicate prompt records collapse, and repeated promotion does not create a second row."""
    del isolated_memory
    context_pack = merge_context_sources(
        current_message="Which database should I use?",
        recent_turns=[],
        session_items=[],
        durable_memory_items=[],
        ambient_context={},
        retrieved_items=[
            {
                "id": "fact-duplicate-1",
                "content": "Use PostgreSQL.",
                "priority": 0.4,
            },
            {
                "id": "fact-duplicate-1",
                "content": "Use PostgreSQL.",
                "priority": 0.9,
            },
        ],
    )
    retrieved = [item for item in context_pack if item["section"] == "retrieved_records"]
    assert len(retrieved) == 1
    assert retrieved[0]["source_ids"] == ["fact-duplicate-1"]
    assert retrieved[0]["priority"] == 0.9

    session_id = create_session("jerry")
    item_id = _correction(session_id, "Use PostgreSQL.")
    candidate = evaluate_promotion_candidate("session_working_set", item_id)
    first_hot_id = promote_to_hot_memory(candidate)
    second_hot_id = promote_to_hot_memory(candidate)
    assert second_hot_id == first_hot_id
    with repository_connection() as connection:
        count = connection.execute(
            "SELECT COUNT(*) AS count FROM working_memory WHERE source_record_id = ?",
            (item_id,),
        ).fetchone()
    assert count is not None and count["count"] == 1

    duplicate_observation_ids = [
        save_observation(session_id, "user", "same durable duplicate"),
        save_observation(session_id, "user", "same durable duplicate"),
    ]
    for observation_id in duplicate_observation_ids:
        ensure_memory_state(
            "observations",
            observation_id,
            LEGACY_WORKSPACE_ID,
            created_at="2026-01-01T00:00:00+00:00",
        )
    first_sleep = run_memory_sleep(
        LEGACY_WORKSPACE_ID,
        max_items=1,
        now="2026-01-02T00:00:00+00:00",
    )
    second_sleep = run_memory_sleep(
        LEGACY_WORKSPACE_ID,
        max_items=1,
        now="2026-01-02T00:00:00+00:00",
    )
    assert first_sleep["reviewed_count"] == 1
    assert first_sleep["consolidated_count"] == 1
    assert second_sleep["id"] == first_sleep["id"]
    assert sorted(
        str(get_memory_state("observations", observation_id)["lifecycle_status"])
        for observation_id in duplicate_observation_ids
    ) == ["active", "archived"]


def test_worker_sleep_is_bounded_and_deterministic(
    isolated_memory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty polling sleeps exactly between bounded iterations and never blocks the test."""
    try:
        import core.memory.slow_path as slow_path
    except ImportError as error:
        pytest.skip(f"slow-path lifecycle seam is unavailable: {error}")

    del isolated_memory
    sleeps: list[float] = []
    monkeypatch.setattr(slow_path, "run_slow_path_batch", lambda _batch_size: [])
    monkeypatch.setattr(slow_path.time, "sleep", sleeps.append)

    summary = slow_path.run_worker(
        batch_size=1,
        poll_interval_s=0.25,
        max_iterations=3,
    )

    assert summary == {"processed": 0, "failed": 0, "iterations": 3}
    assert sleeps == [0.25, 0.25]
