"""Verify ISSUE-011 session micro-path extraction behavior.

Ownership: MIRA contributors.
Related issue: ISSUE-011.
Architecture area: session micro-path.
"""

from __future__ import annotations

from core.session.extractor import extract_session_operations


def test_use_2026_not_2025_extracts_correction() -> None:
    """Direct correction turns become provisional correction operations."""
    operations = extract_session_operations(
        "obs_2026",
        "Use 2026, not 2025.",
        [],
        [{"id": "sws_old_year", "content": "Use 2025.", "status": "provisional"}],
    )

    assert operations == [
        {
            "op": "upsert",
            "type": "correction",
            "content": "Use 2026, not 2025.",
            "scope": "current_session",
            "priority": 0.96,
            "explicitness_label": "direct_correction",
            "evidence_span": "Use 2026, not 2025.",
            "source_observations": ["obs_2026"],
            "supersedes": [],
            "status": "provisional",
        }
    ]


def test_actually_preference_extracts_direct_correction() -> None:
    """Actually-prefixed preference updates are explicit corrections."""
    operations = extract_session_operations(
        "obs_rust",
        "Actually I prefer Rust.",
        [],
        [{"id": "sws_python", "content": "I prefer Python.", "status": "provisional"}],
    )

    assert operations[0]["op"] == "upsert"
    assert operations[0]["type"] == "correction"
    assert operations[0]["explicitness_label"] == "direct_correction"


def test_architecture_sentence_about_corrections_is_no_op() -> None:
    """Mentioning correction handling is not itself a correction."""
    operations = extract_session_operations(
        "obs_architecture",
        (
            "The Session Working Set immediately tracks current goals, corrections, "
            "constraints, decisions, and open questions."
        ),
        [],
        [],
    )

    assert operations[0]["op"] == "no_op"
    assert operations[0]["reason"] == "no_session_state_operation_detected"


def test_negative_architecture_sentence_is_no_op() -> None:
    """Ordinary negative facts should be left for durable slow-path extraction."""
    operations = extract_session_operations(
        "obs_prompt",
        "The prompt is an execution buffer, not the memory store.",
        [],
        [],
    )

    assert operations[0]["op"] == "no_op"
    assert operations[0]["reason"] == "no_session_state_operation_detected"


def test_ordinary_user_question_is_not_persisted_as_open_work() -> None:
    """A question being answered now is not an unresolved Session Working Set item."""
    operations = extract_session_operations(
        "obs_match",
        "Do I have a match?",
        [],
        [],
    )

    assert operations[0]["op"] == "no_op"
    assert operations[0]["reason"] == "no_session_state_operation_detected"


def test_explicit_deliberation_is_extracted_as_open_question() -> None:
    """A genuine unresolved decision remains available to steer later turns."""
    operations = extract_session_operations(
        "obs_open",
        "Open question: should we add recursive summaries?",
        [],
        [],
    )

    assert operations[0]["op"] == "upsert"
    assert operations[0]["type"] == "open_question"
    assert operations[0]["explicitness_label"] == "direct_instruction"


def test_community_summary_distinction_extracts_decision_or_constraint() -> None:
    """Explicit architecture distinctions become decision-like session items."""
    operations = extract_session_operations(
        "obs_summary",
        "Community summaries are different from recursive summaries.",
        [],
        [],
    )

    assert operations[0]["op"] == "upsert"
    assert operations[0]["type"] in {"decision", "active_constraint"}
    assert operations[0]["explicitness_label"] in {"direct_decision", "direct_instruction"}
    assert (
        operations[0]["evidence_span"]
        == "Community summaries are different from recursive summaries."
    )


def test_ignore_that_for_now_extracts_expire_with_target_items() -> None:
    """Resolve/expire turns target active current working-set items."""
    operations = extract_session_operations(
        "obs_ignore",
        "Let's ignore that for now.",
        [],
        [
            {
                "id": "sws_question",
                "content": "Should we add recursive summaries?",
                "status": "provisional",
            }
        ],
    )

    assert operations[0]["op"] == "expire"
    assert operations[0]["type"] == "resolution"
    assert operations[0]["supersedes"] == ["sws_question"]
    assert operations[0]["evidence_span"] == "Let's ignore that for now."


def test_maybe_python_later_is_no_op() -> None:
    """Low-confidence ambiguous turns stay conservative."""
    operations = extract_session_operations(
        "obs_maybe",
        "Maybe I might use Python later.",
        [],
        [],
    )

    assert operations[0]["op"] == "no_op"
    assert operations[0]["reason"] == "ambiguous_low_confidence"


def test_sarcasm_is_treated_conservatively() -> None:
    """Sarcastic turns do not create structured session memory."""
    operations = extract_session_operations(
        "obs_sarcasm",
        "Yeah right, let's totally rewrite everything in COBOL.",
        [],
        [],
    )

    assert operations[0]["op"] == "no_op"
    assert operations[0]["reason"] == "sarcasm_or_irony"


def test_non_no_op_operations_include_required_fields() -> None:
    """Every non-no-op operation includes the strict operation payload fields."""
    operations = extract_session_operations(
        "obs_required",
        "The rule is we must run make check before PR.",
        [],
        [],
    )

    required_fields = {
        "op",
        "type",
        "content",
        "scope",
        "priority",
        "explicitness_label",
        "evidence_span",
        "source_observations",
        "supersedes",
        "status",
    }
    assert required_fields <= set(operations[0])


def test_extractor_does_not_write_to_working_set() -> None:
    """Extractor returns operations only and does not mutate input working-set items."""
    working_set = [{"id": "sws_goal", "content": "Old goal", "status": "provisional"}]

    extract_session_operations("obs_no_write", "Use 2026, not 2025.", [], working_set)

    assert working_set == [{"id": "sws_goal", "content": "Old goal", "status": "provisional"}]
