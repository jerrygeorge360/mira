"""Verify centralized ISSUE-020 prompt templates and schemas.

Ownership: MIRA contributors.
Related issue: ISSUE-020.
Architecture area: llm.
"""

from __future__ import annotations

import json

from core.llm.prompts import (
    OVERCLAIMING_GUARDRAIL,
    SESSION_OPERATION_TAXONOMY,
    get_example_output,
    get_output_schema,
    list_prompt_names,
    render_prompt,
)

REQUIRED_PROMPTS = {
    "session_micro_path_extraction",
    "atomic_fact_extraction",
    "entity_extraction",
    "contradiction_supersession_detection",
    "foresight_detection",
    "foresight_reconciliation",
    "reflection_synthesis",
    "community_summary_generation",
    "retrieval_router_classification",
    "context_scope_classification",
    "retrieval_mode_classification",
    "turn_purpose_classification",
    "discourse_reference_resolution",
    "sufficiency_check",
    "answer_generation",
}


def test_all_required_prompts_exist() -> None:
    """All architecture-required prompt templates live in the central module."""
    assert set(list_prompt_names()) == REQUIRED_PROMPTS


def test_prompt_templates_render_with_inputs() -> None:
    """Every prompt renders with representative inputs."""
    rendered_prompts = {
        name: render_prompt(
            name,
            {
                "recent_turns": [{"role": "user", "content": "Use SQLite."}],
                "current_working_set": [],
                "latest_turn": {"role": "user", "content": "Actually use repositories."},
                "evidence": [{"id": "obs_1", "content": "SQLite is source of truth."}],
                "existing_records": [],
                "new_evidence": [{"id": "obs_2", "content": "Use repositories."}],
                "evidence_records": [],
                "community_nodes": [],
                "query": "What changed?",
                "context": [],
                "turn_purpose": "question",
                "context_scope": "durable_memory",
                "retrieved_context": [],
                "user_message": "Summarize this.",
                "answer_mode": "general_knowledge",
                "evidence_assessment": "Not evaluated.",
                "prompt_context": [],
                "current_time": "2026-07-22T08:00:00+01:00",
                "reference_text": None,
                "latest_statement": "The class was cancelled.",
                "latest_message": "Ignore the autoscaling threshold.",
                "candidates": [],
            },
        )
        for name in list_prompt_names()
    }

    for name, rendered_prompt in rendered_prompts.items():
        assert "Task definition:" in rendered_prompt
        assert "Non-goals:" in rendered_prompt
        assert OVERCLAIMING_GUARDRAIL in rendered_prompt
        assert "{latest_turn}" not in rendered_prompt, name
        assert "{evidence}" not in rendered_prompt, name
        assert "{query}" not in rendered_prompt, name


def test_json_schema_examples_parse() -> None:
    """Every strict JSON schema and example output is JSON-serializable."""
    for name in list_prompt_names():
        schema = get_output_schema(name)
        example = get_example_output(name)

        assert isinstance(schema, dict), name
        assert schema["type"] == "object"
        assert json.loads(json.dumps(example)) == example


def test_atomic_fact_prompt_treats_reusable_configuration_as_durable() -> None:
    rendered = render_prompt(
        "atomic_fact_extraction",
        {"evidence": "I configured a liveness probe every 15 seconds."},
    )

    assert "configuration state" in rendered
    assert "reusable beyond the immediate reply" in rendered


def test_session_extraction_prompt_includes_operation_taxonomy() -> None:
    """The session extraction prompt exposes the Session Working Set operation taxonomy."""
    rendered_prompt = render_prompt(
        "session_micro_path_extraction",
        {
            "recent_turns": [],
            "current_working_set": [],
            "latest_turn": {"role": "user", "content": "This is the current goal."},
        },
    )

    for operation_type in SESSION_OPERATION_TAXONOMY:
        assert operation_type in rendered_prompt
    for operation_name in ("upsert", "supersede", "resolve", "expire", "reject"):
        assert operation_name in rendered_prompt


def test_answer_generation_prompt_handles_declarative_updates() -> None:
    """Answer generation should not dump unrelated memory for plain updates."""
    rendered_prompt = render_prompt(
        "answer_generation",
        {
            "user_message": "MIRA uses SQLite as the source of truth.",
            "answer_mode": "memory_grounded",
            "prompt_context": [],
        },
    )

    assert "declarative update" in rendered_prompt
    assert "do not summarize unrelated memories" in rendered_prompt
    assert "Retrieved context is optional evidence" in rendered_prompt


def test_router_schema_requires_scope_and_confidence() -> None:
    schema = get_output_schema("retrieval_router_classification")

    assert set(schema["required"]) == {"context_scope", "mode", "confidence", "reason"}
    properties = schema["properties"]
    assert "recent_conversation" in properties["context_scope"]["enum"]


def test_sequential_router_schemas_separate_scope_from_mode() -> None:
    scope_schema = get_output_schema("context_scope_classification")
    mode_schema = get_output_schema("retrieval_mode_classification")

    assert "no_retrieval" in scope_schema["properties"]["context_scope"]["enum"]
    assert set(mode_schema["properties"]["mode"]["enum"]) == {
        "quick",
        "deep",
        "relational",
    }
    assert "auto" not in mode_schema["properties"]["mode"]["enum"]
