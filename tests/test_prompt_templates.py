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
    "reflection_synthesis",
    "community_summary_generation",
    "retrieval_router_classification",
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
                "retrieved_context": [],
                "user_message": "Summarize this.",
                "answer_mode": "general_knowledge",
                "prompt_context": [],
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
