"""Document foresight and domain reflection remain scoped and source-backed."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.db.evidence import register_source, retract_document_sources
from core.db.repositories import configure_database, repository_connection
from core.memory import foresight, reflection


@pytest.fixture
def sources(tmp_path: Path) -> tuple[str, str, str]:
    configure_database(tmp_path / "source-memory.sqlite")
    now = "2026-01-01T00:00:00+00:00"
    with repository_connection() as db:
        for workspace in ("one", "two"):
            db.execute(
                "INSERT INTO workspaces (id, name, slug, workspace_type, created_at, updated_at) "
                "VALUES (?, ?, ?, 'development', ?, ?)",
                (workspace, workspace, workspace, now, now),
            )
            db.execute(
                "INSERT INTO knowledge_bases "
                "(id, workspace_id, name, status, created_at, updated_at) "
                "VALUES (?, ?, 'Source KB', 'active', ?, ?)",
                (f"kb-{workspace}", workspace, now, now),
            )
            db.execute(
                "INSERT INTO documents (id, workspace_id, knowledge_base_id, filename, mime_type, "
                "size_bytes, s3_bucket, s3_key, checksum_sha256, status, created_at, updated_at) "
                "VALUES (?, ?, ?, 'plan.txt', 'text/plain', 80, 'bucket', 'key', 'hash', "
                "'ready', ?, ?)",
                (f"doc-{workspace}", workspace, f"kb-{workspace}", now, now),
            )
            for index, content in enumerate(
                (
                    "The release milestone is scheduled for 2027-12-10.",
                    "The review process consistently prioritizes adaptive revision.",
                )
            ):
                db.execute(
                    "INSERT INTO document_chunks (id, workspace_id, knowledge_base_id, "
                    "document_id, chunk_index, content, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"chunk-{workspace}-{index}",
                        workspace,
                        f"kb-{workspace}",
                        f"doc-{workspace}",
                        index,
                        content,
                        now,
                    ),
                )
    first = register_source("document_chunk", "chunk-one-0", workspace_id="one")
    second = register_source("document_chunk", "chunk-one-1", workspace_id="one")
    other = register_source("document_chunk", "chunk-two-0", workspace_id="two")
    return first, second, other


def test_document_foresight_requires_confirmation_and_scoped_retrieval(
    sources: tuple[str, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    first, _, other = sources
    monkeypatch.setattr(
        foresight,
        "call_qwen_json",
        lambda *_args, **_kwargs: {
            "json": {
                "foresight": [
                    {
                        "content": "The release milestone is scheduled for 2027-12-10.",
                        "reason": "Project schedule",
                        "status": "active",
                        "always_inject": True,
                    }
                ]
            }
        },
    )
    candidates = foresight.detect_document_foresight_candidates(
        first, {"current_date": "2026-11-16"}, workspace_id="one"
    )
    assert len(candidates) == 1
    assert candidates[0]["status"] == "candidate"
    assert candidates[0]["always_inject"] is False
    with repository_connection() as db:
        assert db.execute("SELECT COUNT(*) FROM foresight_records").fetchone()[0] == 0
    with pytest.raises(ValueError, match="explicit confirmation"):
        foresight.activate_document_foresight_candidate(
            candidates[0], workspace_id="one", confirmed=False
        )
    with pytest.raises(ValueError, match="workspace"):
        foresight.activate_document_foresight_candidate(
            candidates[0], workspace_id="two", confirmed=True
        )
    with pytest.raises(ValueError, match="workspace"):
        foresight.detect_document_foresight_candidates(
            other, {"current_date": "2026-11-16"}, workspace_id="one"
        )
    record_id = foresight.activate_document_foresight_candidate(
        candidates[0], workspace_id="one", confirmed=True
    )
    with repository_connection() as db:
        activation_time = str(
            db.execute(
                "SELECT valid_from FROM foresight_records WHERE id = ?", (record_id,)
            ).fetchone()[0]
        )
    foresight.update_foresight_status(record_id, activation_time)
    assert (
        foresight.list_relevant_foresight("release milestone", activation_time, workspace_id="one")
        == []
    )
    assert (
        foresight.list_relevant_foresight(
            "release milestone",
            activation_time,
            workspace_id="one",
            include_documents=True,
            allowed_knowledge_base_ids={"kb-two"},
        )
        == []
    )
    found = foresight.list_relevant_foresight(
        "release milestone",
        activation_time,
        workspace_id="one",
        include_documents=True,
        allowed_knowledge_base_ids={"kb-one"},
    )
    assert [item["id"] for item in found] == [record_id]
    assert found[0]["always_inject"] is False
    assert found[0]["source_observation_id"] is None
    retract_document_sources("doc-one", workspace_id="one")
    assert (
        foresight.list_relevant_foresight(
            "release milestone",
            activation_time,
            workspace_id="one",
            include_documents=True,
            allowed_knowledge_base_ids={"kb-one"},
        )
        == []
    )


def test_historical_document_date_is_not_a_candidate(
    sources: tuple[str, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    first, _, _ = sources
    monkeypatch.setattr(
        foresight,
        "call_qwen_json",
        lambda *_args, **_kwargs: {
            "json": {"foresight": [{"content": "Release scheduled for 2020-01-01."}]}
        },
    )
    assert (
        foresight.detect_document_foresight_candidates(
            first, {"current_date": "2026-11-16"}, workspace_id="one"
        )
        == []
    )


def test_document_foresight_is_persisted_as_candidate_until_confirmed(
    sources: tuple[str, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    first, _, _ = sources
    monkeypatch.setattr(
        foresight,
        "call_qwen_json",
        lambda *_args, **_kwargs: {
            "json": {
                "foresight": [
                    {
                        "content": "The release milestone is scheduled for 2027-12-10.",
                        "reason": "Project schedule",
                    }
                ]
            }
        },
    )
    candidate = foresight.detect_document_foresight_candidates(
        first, {"current_date": "2026-11-16"}, workspace_id="one"
    )[0]
    record_id = foresight.store_document_foresight_candidate(candidate, workspace_id="one")
    with repository_connection() as db:
        row = db.execute(
            "SELECT status, source_observation_id, valid_from, valid_until "
            "FROM foresight_records WHERE id = ?",
            (record_id,),
        ).fetchone()
    assert tuple(row) == (
        "candidate",
        None,
        None,
        "2027-12-10T23:59:59.999999+00:00",
    )
    assert (
        foresight.list_relevant_foresight(
            "release milestone",
            "2026-11-16",
            workspace_id="one",
            include_documents=True,
            allowed_knowledge_base_ids={"kb-one"},
        )
        == []
    )
    with pytest.raises(ValueError, match="explicit confirmation"):
        foresight.confirm_document_foresight_candidate(
            record_id, workspace_id="one", confirmed=False
        )
    foresight.confirm_document_foresight_candidate(record_id, workspace_id="one", confirmed=True)
    with repository_connection() as db:
        row = db.execute(
            "SELECT status, valid_from, valid_until FROM foresight_records WHERE id = ?",
            (record_id,),
        ).fetchone()
    assert row[0] == "pending"
    assert row[1] is not None
    assert row[2] == "2027-12-10T23:59:59.999999+00:00"


def test_date_only_foresight_is_valid_through_event_day() -> None:
    event = foresight._document_event_date({}, {"content": "Exam date is 2027-12-10."})
    assert event is not None
    assert foresight._temporally_valid(
        {"valid_until": event.isoformat()},
        foresight.datetime(2027, 12, 10, 14, tzinfo=foresight.UTC),
    )
    assert not foresight._temporally_valid(
        {"valid_until": event.isoformat()},
        foresight.datetime(2027, 12, 11, 0, tzinfo=foresight.UTC),
    )


def test_domain_reflection_uses_evidence_without_personal_synthesis(
    sources: tuple[str, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second, other = sources
    monkeypatch.setattr(
        reflection,
        "call_qwen_json",
        lambda *_args, **_kwargs: {
            "json": {
                "reflections": [
                    {
                        "reflection_type": "self_knowledge",
                        "content": "The user prefers adaptive revision.",
                        "confidence": 0.9,
                        "evidence_ids": [first, second],
                    },
                    {
                        "reflection_type": "world_knowledge",
                        "content": (
                            "Across the project plan, release planning and review "
                            "use an adaptive strategy."
                        ),
                        "confidence": 0.8,
                        "evidence_ids": [first, second],
                    },
                ]
            }
        },
    )
    with pytest.raises(ValueError, match="workspace"):
        reflection.synthesize_domain_reflections([first, other], workspace_id="one")
    candidates = reflection.synthesize_domain_reflections([first, second], workspace_id="one")
    assert len(candidates) == 1
    assert candidates[0]["reflection_type"] == "world_knowledge"
    assert candidates[0]["hot_memory_candidate"] is False
    with pytest.raises(ValueError, match="scope"):
        reflection.store_domain_reflection_with_evidence(
            {**candidates[0], "knowledge_base_id": "kb-two"}, [first, second], workspace_id="one"
        )
    reflection_id = reflection.store_domain_reflection_with_evidence(
        candidates[0], [first, second], workspace_id="one"
    )
    with repository_connection() as db:
        row = db.execute("SELECT * FROM reflections WHERE id = ?", (reflection_id,)).fetchone()
        assert row["workspace_id"] == "one"
        assert row["reflection_type"] == "world_knowledge"
        assert (
            db.execute(
                "SELECT COUNT(*) FROM evidence_links "
                "WHERE target_type = 'reflection' AND target_id = ?",
                (reflection_id,),
            ).fetchone()[0]
            == 2
        )
    retract_document_sources("doc-one", workspace_id="one")
    reflection.invalidate_reflection_if_unsupported(reflection_id)
    with repository_connection() as db:
        status = db.execute(
            "SELECT status FROM reflections WHERE id = ?", (reflection_id,)
        ).fetchone()[0]
    assert status == "stale"


def test_domain_reflection_dedupe_does_not_cross_knowledge_bases(
    sources: tuple[str, str, str],
) -> None:
    first, second, _ = sources
    now = "2026-01-01T00:00:00+00:00"
    with repository_connection() as db:
        db.execute(
            "INSERT INTO knowledge_bases "
            "(id, workspace_id, name, status, created_at, updated_at) "
            "VALUES ('kb-one-other', 'one', 'Other KB', 'active', ?, ?)",
            (now, now),
        )
        db.execute(
            "INSERT INTO documents (id, workspace_id, knowledge_base_id, filename, mime_type, "
            "size_bytes, s3_bucket, s3_key, checksum_sha256, status, created_at, updated_at) "
            "VALUES ('doc-one-two', 'one', 'kb-one-other', 'other.txt', 'text/plain', 10, "
            "'bucket', 'other-key', 'hash', 'ready', ?, ?)",
            (now, now),
        )
        for index in range(2):
            db.execute(
                "INSERT INTO document_chunks (id, workspace_id, knowledge_base_id, "
                "document_id, chunk_index, content, created_at) "
                "VALUES (?, 'one', 'kb-one-other', 'doc-one-two', ?, ?, ?)",
                (f"chunk-one-two-{index}", index, f"Other project evidence {index}.", now),
            )
    other_sources = [
        register_source("document_chunk", f"chunk-one-two-{index}", workspace_id="one")
        for index in range(2)
    ]
    content = "The source set consistently describes the same domain principle."
    first_reflection = reflection.store_domain_reflection_with_evidence(
        {
            "reflection_type": "world_knowledge",
            "scope": "domain",
            "content": content,
            "confidence": 0.8,
            "workspace_id": "one",
            "project_id": None,
            "namespace": None,
            "knowledge_base_id": "kb-one",
            "evidence_ids": [first, second],
        },
        [first, second],
        workspace_id="one",
    )
    other_reflection = reflection.store_domain_reflection_with_evidence(
        {
            "reflection_type": "world_knowledge",
            "scope": "domain",
            "content": content,
            "confidence": 0.8,
            "workspace_id": "one",
            "project_id": None,
            "namespace": None,
            "knowledge_base_id": "kb-one-other",
            "evidence_ids": other_sources,
        },
        other_sources,
        workspace_id="one",
    )
    assert first_reflection != other_reflection


def test_document_reflection_stales_when_support_drops_below_two(
    sources: tuple[str, str, str],
) -> None:
    first, _, _ = sources
    now = "2026-01-01T00:00:00+00:00"
    with repository_connection() as db:
        db.execute(
            "INSERT INTO documents (id, workspace_id, knowledge_base_id, filename, mime_type, "
            "size_bytes, s3_bucket, s3_key, checksum_sha256, status, created_at, updated_at) "
            "VALUES ('doc-one-extra', 'one', 'kb-one', 'extra.txt', 'text/plain', 10, "
            "'bucket', 'extra-key', 'hash', 'ready', ?, ?)",
            (now, now),
        )
        db.execute(
            "INSERT INTO document_chunks (id, workspace_id, knowledge_base_id, document_id, "
            "chunk_index, content, created_at) VALUES ('chunk-one-extra', 'one', 'kb-one', "
            "'doc-one-extra', 0, 'Additional domain evidence.', ?)",
            (now,),
        )
    extra = register_source("document_chunk", "chunk-one-extra", workspace_id="one")
    reflection_id = reflection.store_domain_reflection_with_evidence(
        {
            "reflection_type": "world_knowledge",
            "scope": "domain",
            "content": "At least two distinct sources support this synthesis.",
            "confidence": 0.8,
            "workspace_id": "one",
            "project_id": None,
            "namespace": None,
            "knowledge_base_id": "kb-one",
            "evidence_ids": [first, extra],
        },
        [first, extra],
        workspace_id="one",
    )

    retract_document_sources("doc-one", workspace_id="one")

    with repository_connection() as db:
        status = db.execute(
            "SELECT status FROM reflections WHERE id = ?", (reflection_id,)
        ).fetchone()[0]
    assert status == "stale"


def test_document_foresight_cannot_be_created_via_observation_path(
    sources: tuple[str, str, str],
) -> None:
    first, _, _ = sources
    with pytest.raises(ValueError, match="source observation"):
        foresight.create_foresight(
            {"content": "The release is due 2027-12-10", "evidence_source_id": first}
        )
