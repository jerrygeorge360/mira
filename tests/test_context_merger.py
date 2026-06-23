"""Verify the ISSUE-017 context merger.

Ownership: MIRA contributors.
Related issue: ISSUE-017.
Architecture area: context.
"""

from __future__ import annotations

from core.context.merger import merge_context_sources


def test_session_correction_overrides_older_durable_item_in_prompt() -> None:
    """Session corrections win in the prompt while durable memory is preserved."""
    context_pack = merge_context_sources(
        current_message="What should I use?",
        recent_turns=[],
        session_items=[
            {
                "id": "sws_1",
                "type": "correction",
                "status": "provisional",
                "content": "Use SQLite, not Postgres, for the MIRA source of truth.",
                "priority": 0.95,
                "evidence_span": "Use SQLite, not Postgres.",
                "source_observations": ["obs_2"],
            }
        ],
        durable_memory_items=[
            {
                "id": "wm_1",
                "content": "Use Postgres for the MIRA source of truth.",
                "priority": 0.8,
                "source_record_id": "fact_1",
            }
        ],
        ambient_context={},
        retrieved_items=[],
    )

    session_record = _first_section(context_pack, "session_working_set")
    durable_record = _first_section(context_pack, "durable_memory")
    diagnostics = _first_section(context_pack, "diagnostics")

    assert session_record["prompt_winner"] is True
    assert durable_record["shadowed_by_session"] is True
    assert durable_record["prompt_include"] is False
    assert durable_record["content"] == "Use Postgres for the MIRA source of truth."
    assert diagnostics["conflicts"][0]["slow_path_action"] == (
        "review_for_SUPERSEDED_BY_or_CONTRADICTS"
    )


def test_duplicate_retrieved_items_are_merged() -> None:
    """Duplicate records with the same source ID are merged into one context section."""
    context_pack = merge_context_sources(
        current_message="Tell me about the deadline.",
        recent_turns=[],
        session_items=[],
        durable_memory_items=[],
        ambient_context={},
        retrieved_items=[
            {"id": "fact_1", "content": "Deadline is Friday.", "priority": 0.4},
            {"id": "fact_1", "content": "Deadline is Friday.", "priority": 0.9},
        ],
    )

    retrieved_sections = [
        section for section in context_pack if section["section"] == "retrieved_records"
    ]

    assert len(retrieved_sections) == 1
    assert retrieved_sections[0]["source_ids"] == ["fact_1"]
    assert retrieved_sections[0]["priority"] == 0.9
    assert retrieved_sections[0]["merged_sections"] == ["retrieved_records"]


def test_conflict_log_created_without_deleting_memory() -> None:
    """Conflicts are surfaced for slow path while both records remain in the pack."""
    context_pack = merge_context_sources(
        current_message="Continue.",
        recent_turns=[],
        session_items=[
            {
                "id": "sws_2",
                "type": "correction",
                "status": "confirmed",
                "content": "Do not use recursive summaries for communities.",
                "source_observations": ["obs_3"],
                "priority": 0.9,
            }
        ],
        durable_memory_items=[
            {
                "id": "wm_2",
                "content": "Use recursive summaries for communities.",
                "source_record_id": "fact_2",
                "priority": 0.7,
            }
        ],
        ambient_context={"timezone": "Africa/Lagos"},
        retrieved_items=[],
    )

    assert _section_count(context_pack, "session_working_set") == 1
    assert _section_count(context_pack, "durable_memory") == 1
    assert _section_count(context_pack, "diagnostics") == 1
    assert _first_section(context_pack, "diagnostics")["conflicts"]


def test_evidence_backed_items_outrank_unsupported_duplicates() -> None:
    """When duplicates merge, supported evidence and higher priority are retained."""
    context_pack = merge_context_sources(
        current_message="Continue.",
        recent_turns=[],
        session_items=[
            {
                "id": "sws_3",
                "content": "Use typed repositories.",
                "priority": 0.2,
                "source_observations": ["obs_4"],
            },
            {
                "id": "sws_3",
                "content": "Use typed repositories.",
                "priority": 0.8,
                "supported": False,
            },
        ],
        durable_memory_items=[],
        ambient_context={},
        retrieved_items=[],
    )

    session_record = _first_section(context_pack, "session_working_set")

    assert session_record["supported"] is True
    assert session_record["priority"] == 0.8
    assert session_record["source_ids"] == ["obs_4", "sws_3"]


def _first_section(context_pack: list[dict[str, object]], section: str) -> dict[str, object]:
    for record in context_pack:
        if record["section"] == section:
            return record
    raise AssertionError(f"missing context section {section}")


def _section_count(context_pack: list[dict[str, object]], section: str) -> int:
    return sum(1 for record in context_pack if record["section"] == section)
