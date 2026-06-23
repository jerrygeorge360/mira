"""Central prompt templates and strict output schemas for MIRA pipelines.

Ownership: Jerry.
Related issue: ISSUE-020.
Architecture area: llm.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

PromptInputs = dict[str, object]
JsonSchema = dict[str, object]

OVERCLAIMING_GUARDRAIL = (
    "Do not overclaim procedural memory: only state durable habits, instructions, "
    "or preferences when the evidence explicitly supports them."
)

SESSION_OPERATION_TAXONOMY = (
    "current_goal",
    "active_constraint",
    "correction",
    "decision",
    "open_question",
    "resolution",
)


@dataclass(frozen=True)
class PromptTemplate:
    """A renderable prompt template plus optional strict JSON schema and example output."""

    name: str
    template: str
    output_schema: JsonSchema | None
    example_output: object | None

    def render(self, inputs: PromptInputs | None = None) -> str:
        """Render the prompt with escaped input values."""
        values = {key: _stringify(value) for key, value in (inputs or {}).items()}
        return self.template.format_map(_SafeFormatMap(values))


SESSION_EXTRACTION_SCHEMA: JsonSchema = {
    "type": "object",
    "required": ["operations"],
    "additionalProperties": False,
    "properties": {
        "operations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "operation",
                    "type",
                    "content",
                    "scope",
                    "explicitness_label",
                    "confidence",
                    "evidence_span",
                ],
                "additionalProperties": False,
                "properties": {
                    "operation": {"enum": ["upsert", "supersede", "resolve", "expire", "reject"]},
                    "type": {"enum": list(SESSION_OPERATION_TAXONOMY)},
                    "content": {"type": "string"},
                    "scope": {
                        "enum": [
                            "current_response",
                            "current_task",
                            "current_session",
                            "project",
                            "cross_session",
                        ]
                    },
                    "explicitness_label": {
                        "enum": [
                            "direct_instruction",
                            "direct_correction",
                            "direct_decision",
                            "explicit_preference",
                            "inferred_preference",
                            "agent_inference",
                            "ambiguous",
                        ]
                    },
                    "confidence": {"type": "number"},
                    "evidence_span": {"type": "string"},
                    "target_id": {"type": ["string", "null"]},
                },
            },
        }
    },
}

ATOMIC_FACT_SCHEMA: JsonSchema = {
    "type": "object",
    "required": ["facts"],
    "additionalProperties": False,
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["subject", "predicate", "object", "confidence", "evidence_span"],
                "additionalProperties": False,
                "properties": {
                    "subject": {"type": "string"},
                    "predicate": {"type": "string"},
                    "object": {"type": "string"},
                    "confidence": {"type": "number"},
                    "evidence_span": {"type": "string"},
                },
            },
        }
    },
}

ENTITY_EXTRACTION_SCHEMA: JsonSchema = {
    "type": "object",
    "required": ["entities"],
    "additionalProperties": False,
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "entity_type", "aliases"],
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "entity_type": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                },
            },
        }
    },
}

CONTRADICTION_SCHEMA: JsonSchema = {
    "type": "object",
    "required": ["relations"],
    "additionalProperties": False,
    "properties": {
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["relation", "source_id", "target_id", "confidence", "reason"],
                "additionalProperties": False,
                "properties": {
                    "relation": {"enum": ["CONTRADICTS", "SUPERSEDED_BY"]},
                    "source_id": {"type": "string"},
                    "target_id": {"type": "string"},
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                },
            },
        }
    },
}

FORESIGHT_SCHEMA: JsonSchema = {
    "type": "object",
    "required": ["foresight"],
    "additionalProperties": False,
    "properties": {
        "foresight": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["content", "reason", "status", "always_inject"],
                "additionalProperties": False,
                "properties": {
                    "content": {"type": "string"},
                    "reason": {"type": "string"},
                    "status": {"enum": ["pending", "active"]},
                    "always_inject": {"type": "boolean"},
                },
            },
        }
    },
}

REFLECTION_SCHEMA: JsonSchema = {
    "type": "object",
    "required": ["reflections"],
    "additionalProperties": False,
    "properties": {
        "reflections": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["reflection_type", "content", "confidence", "evidence_ids"],
                "additionalProperties": False,
                "properties": {
                    "reflection_type": {
                        "enum": ["user_knowledge", "world_knowledge", "self_knowledge"]
                    },
                    "content": {"type": "string"},
                    "confidence": {"type": "number"},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        }
    },
}

COMMUNITY_SUMMARY_SCHEMA: JsonSchema = {
    "type": "object",
    "required": ["title", "summary", "member_node_ids"],
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "member_node_ids": {"type": "array", "items": {"type": "string"}},
    },
}

RETRIEVAL_ROUTER_SCHEMA: JsonSchema = {
    "type": "object",
    "required": ["mode", "reason"],
    "additionalProperties": False,
    "properties": {
        "mode": {"enum": ["quick", "deep", "relational", "auto"]},
        "reason": {"type": "string"},
    },
}

SUFFICIENCY_SCHEMA: JsonSchema = {
    "type": "object",
    "required": ["sufficient", "missing"],
    "additionalProperties": False,
    "properties": {
        "sufficient": {"type": "boolean"},
        "missing": {"type": "array", "items": {"type": "string"}},
    },
}

ANSWER_GENERATION_SCHEMA: JsonSchema = {
    "type": "object",
    "required": ["answer", "used_memory_ids"],
    "additionalProperties": False,
    "properties": {
        "answer": {"type": "string"},
        "used_memory_ids": {"type": "array", "items": {"type": "string"}},
    },
}

PROMPT_TEMPLATES: dict[str, PromptTemplate] = {
    "session_micro_path_extraction": PromptTemplate(
        name="session_micro_path_extraction",
        output_schema=SESSION_EXTRACTION_SCHEMA,
        example_output={
            "operations": [
                {
                    "operation": "upsert",
                    "type": "correction",
                    "content": "Use SQLite as the source of truth.",
                    "scope": "project",
                    "explicitness_label": "direct_correction",
                    "confidence": 0.98,
                    "evidence_span": "actually SQLite is the source of truth",
                    "target_id": None,
                }
            ]
        },
        template="""Task definition:
Extract current-session operations from the latest turn for the temporary Session Working Set.

Operation taxonomy:
- current_goal
- active_constraint
- correction
- decision
- open_question
- resolution

Allowed operations:
- upsert
- supersede
- resolve
- expire
- reject

Non-goals:
- Do not create durable memory.
- Do not infer private intent.
- Do not rewrite prior assistant responses.
- {overclaiming_guardrail}

Strict JSON schema:
{schema}

Example:
{example}

Inputs:
Recent turns: {recent_turns}
Current working set: {current_working_set}
Latest turn: {latest_turn}
""",
    ),
    "atomic_fact_extraction": PromptTemplate(
        name="atomic_fact_extraction",
        output_schema=ATOMIC_FACT_SCHEMA,
        example_output={
            "facts": [
                {
                    "subject": "MIRA",
                    "predicate": "uses",
                    "object": "SQLite as source of truth",
                    "confidence": 0.95,
                    "evidence_span": "SQLite is the source of truth",
                }
            ]
        },
        template="""Task definition:
Extract durable atomic facts from confirmed evidence.

Non-goals:
- Do not extract temporary session goals.
- Do not include speculation.
- {overclaiming_guardrail}

Strict JSON schema:
{schema}

Example:
{example}

Evidence:
{evidence}
""",
    ),
    "entity_extraction": PromptTemplate(
        name="entity_extraction",
        output_schema=ENTITY_EXTRACTION_SCHEMA,
        example_output={"entities": [{"name": "MIRA", "entity_type": "project", "aliases": []}]},
        template="""Task definition:
Extract named entities and aliases from evidence.

Non-goals:
- Do not invent entities.
- Do not classify uncertain mentions as stable identity.
- {overclaiming_guardrail}

Strict JSON schema:
{schema}

Example:
{example}

Evidence:
{evidence}
""",
    ),
    "contradiction_supersession_detection": PromptTemplate(
        name="contradiction_supersession_detection",
        output_schema=CONTRADICTION_SCHEMA,
        example_output={
            "relations": [
                {
                    "relation": "SUPERSEDED_BY",
                    "source_id": "fact_old",
                    "target_id": "fact_new",
                    "confidence": 0.91,
                    "reason": "User corrected the earlier preference.",
                }
            ]
        },
        template="""Task definition:
Detect whether new evidence contradicts or supersedes existing records.

Non-goals:
- Do not delete records.
- Do not mark disagreement unless evidence directly conflicts.
- {overclaiming_guardrail}

Strict JSON schema:
{schema}

Example:
{example}

Existing records:
{existing_records}
New evidence:
{new_evidence}
""",
    ),
    "foresight_detection": PromptTemplate(
        name="foresight_detection",
        output_schema=FORESIGHT_SCHEMA,
        example_output={
            "foresight": [
                {
                    "content": "Remind the agent to run make check before PR.",
                    "reason": "User made it a workflow constraint.",
                    "status": "active",
                    "always_inject": False,
                }
            ]
        },
        template="""Task definition:
Detect future-facing reminders, constraints, or checks that may help later responses.

Non-goals:
- Do not create calendar events.
- Do not treat vague wishes as active foresight.
- {overclaiming_guardrail}

Strict JSON schema:
{schema}

Example:
{example}

Evidence:
{evidence}
""",
    ),
    "reflection_synthesis": PromptTemplate(
        name="reflection_synthesis",
        output_schema=REFLECTION_SCHEMA,
        example_output={
            "reflections": [
                {
                    "reflection_type": "self_knowledge",
                    "content": "The project prefers repository APIs over ad-hoc SQL.",
                    "confidence": 0.86,
                    "evidence_ids": ["obs_1", "fact_2"],
                }
            ]
        },
        template="""Task definition:
Synthesize compact reflections from multiple evidence records.

Non-goals:
- Do not summarize stale or invalidated evidence as current.
- Do not add unsupported personality or preference claims.
- {overclaiming_guardrail}

Strict JSON schema:
{schema}

Example:
{example}

Evidence records:
{evidence_records}
""",
    ),
    "community_summary_generation": PromptTemplate(
        name="community_summary_generation",
        output_schema=COMMUNITY_SUMMARY_SCHEMA,
        example_output={
            "title": "Persistence Architecture",
            "summary": "SQLite stores durable memory while indexes remain rebuildable.",
            "member_node_ids": ["node_1", "node_2"],
        },
        template="""Task definition:
Generate a concise summary for a graph community.

Non-goals:
- Do not include nodes outside the provided community.
- Do not present inferred edges as confirmed.
- {overclaiming_guardrail}

Strict JSON schema:
{schema}

Example:
{example}

Community nodes:
{community_nodes}
""",
    ),
    "retrieval_router_classification": PromptTemplate(
        name="retrieval_router_classification",
        output_schema=RETRIEVAL_ROUTER_SCHEMA,
        example_output={"mode": "relational", "reason": "The query asks about contradictions."},
        template="""Task definition:
Classify the retrieval mode needed for the user query.

Modes:
- quick: direct facts, keyword, vector, recent memory.
- deep: community summaries and broad synthesis.
- relational: graph traversal, contradiction, supersession, causality, evidence.
- auto: insufficient information to choose a specific route.

Non-goals:
- Do not retrieve records.
- Do not answer the user.
- {overclaiming_guardrail}

Strict JSON schema:
{schema}

Example:
{example}

Query:
{query}
Available context:
{context}
""",
    ),
    "sufficiency_check": PromptTemplate(
        name="sufficiency_check",
        output_schema=SUFFICIENCY_SCHEMA,
        example_output={"sufficient": False, "missing": ["evidence for the latest correction"]},
        template="""Task definition:
Decide whether retrieved context is sufficient to answer the query.

Non-goals:
- Do not answer the query.
- Do not request more retrieval if context is already enough.
- {overclaiming_guardrail}

Strict JSON schema:
{schema}

Example:
{example}

Query:
{query}
Retrieved context:
{retrieved_context}
""",
    ),
    "answer_generation": PromptTemplate(
        name="answer_generation",
        output_schema=ANSWER_GENERATION_SCHEMA,
        example_output={
            "answer": "Use the repository API rather than ad-hoc SQL.",
            "used_memory_ids": ["memory_1"],
        },
        template="""Task definition:
Generate a final answer using the provided prompt context.

Non-goals:
- Do not expose hidden chain-of-thought.
- Do not claim memory not present in context.
- {overclaiming_guardrail}

Strict JSON schema:
{schema}

Example:
{example}

User message:
{user_message}
Prompt context:
{prompt_context}
""",
    ),
}


def get_prompt_template(name: str) -> str:
    """Return a prompt template identified by name."""
    return get_prompt(name).template


def get_prompt(name: str) -> PromptTemplate:
    """Return a centralized prompt definition by name."""
    try:
        return PROMPT_TEMPLATES[name]
    except KeyError as error:
        raise KeyError(f"Unknown prompt template: {name}") from error


def render_prompt(name: str, inputs: PromptInputs | None = None) -> str:
    """Render a centralized prompt with provided inputs."""
    prompt = get_prompt(name)
    base_inputs: PromptInputs = {
        "schema": prompt.output_schema or {},
        "example": prompt.example_output if prompt.example_output is not None else {},
        "overclaiming_guardrail": OVERCLAIMING_GUARDRAIL,
    }
    base_inputs.update(inputs or {})
    return prompt.render(base_inputs)


def get_output_schema(name: str) -> JsonSchema | None:
    """Return the strict JSON output schema for a prompt, when applicable."""
    return get_prompt(name).output_schema


def get_example_output(name: str) -> object | None:
    """Return the parseable example output for a prompt, when applicable."""
    return get_prompt(name).example_output


def list_prompt_names() -> tuple[str, ...]:
    """Return all centralized prompt template names."""
    return tuple(PROMPT_TEMPLATES)


def _stringify(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True)


class _SafeFormatMap(dict[str, str]):
    """Format map that leaves missing placeholders visible in rendered prompts."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"
