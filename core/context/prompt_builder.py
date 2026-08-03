"""Final prompt assembly across context sources.

Ownership: Jerry.
Related issue: ISSUE-401.
Architecture area: context.
"""

from __future__ import annotations

from core.context.budget import trim_context_sections
from core.context.merger import merge_context_sources
from core.llm.prompts import render_prompt


def build_prompt(
    user_message: str,
    recent_turns: list[str],
    session_items: list[dict[str, object]],
    retrieved_memories: list[dict[str, object]],
    ambient_context: dict[str, object],
    token_budget: int,
    *,
    answer_mode: str = "memory_grounded",
    durable_memory_items: list[dict[str, object]] | None = None,
) -> str:
    """Build the final model prompt under the configured context budget."""
    if token_budget < 1:
        raise ValueError("token_budget must be a positive integer")
    recent_records: list[dict[str, object]] = [{"content": turn} for turn in recent_turns]
    context_pack = merge_context_sources(
        current_message=user_message,
        recent_turns=recent_records,
        session_items=session_items,
        durable_memory_items=durable_memory_items or [],
        ambient_context=ambient_context,
        retrieved_items=retrieved_memories,
    )
    trimmed = trim_context_sections(context_pack, token_budget)
    return build_prompt_from_context(user_message, trimmed, answer_mode=answer_mode)


def build_prompt_from_context(
    user_message: str,
    context_pack: list[dict[str, object]],
    *,
    answer_mode: str = "memory_grounded",
    sufficiency: dict[str, object] | None = None,
) -> str:
    """Render the answer-generation prompt from an existing context pack."""
    return render_prompt(
        "answer_generation",
        {
            "user_message": user_message,
            "answer_mode": answer_mode,
            "prompt_context": _render_context(context_pack),
            "evidence_assessment": _render_sufficiency(sufficiency),
        },
    )


def build_answer_messages(
    user_message: str,
    context_pack: list[dict[str, object]],
    *,
    answer_mode: str = "memory_grounded",
    sufficiency: dict[str, object] | None = None,
) -> list[dict[str, str]]:
    """Keep evidence in a distinct prior turn so a gateway can compress it safely."""
    rendered_context = _render_context(context_pack)
    if not rendered_context:
        return [
            {
                "role": "user",
                "content": build_prompt_from_context(
                    user_message,
                    context_pack,
                    answer_mode=answer_mode,
                    sufficiency=sufficiency,
                ),
            }
        ]
    task_prompt = render_prompt(
        "answer_generation",
        {
            "user_message": user_message,
            "answer_mode": answer_mode,
            "prompt_context": "Use the memory context supplied in the preceding turn.",
            "evidence_assessment": _render_sufficiency(sufficiency),
        },
    )
    return [
        {
            "role": "user",
            "content": f"Memory context selected by MIRA:\n{rendered_context}",
        },
        {
            "role": "assistant",
            "content": (
                "Context received. I will use only relevant evidence and preserve uncertainty."
            ),
        },
        {"role": "user", "content": task_prompt},
    ]


def _render_sufficiency(sufficiency: dict[str, object] | None) -> str:
    if sufficiency is None:
        return "Not evaluated because durable retrieval was not required."
    verdict = sufficiency.get("sufficiency")
    if not isinstance(verdict, dict):
        return "Retrieved evidence was not verified."
    requirement_results = verdict.get("requirement_results")
    requirement_results = requirement_results if isinstance(requirement_results, list) else []
    supported: list[str] = []
    missing: list[str] = []
    for result in requirement_results:
        if not isinstance(result, dict):
            continue
        clause = str(result.get("clause", "")).strip()
        if not clause:
            continue
        (supported if result.get("supported") else missing).append(clause)
    return (
        f"Sufficient: {bool(verdict.get('is_sufficient'))}. "
        f"Supported requirements: {supported}. "
        f"Missing requirements: {missing}. "
        f"Must answer with uncertainty: {bool(sufficiency.get('answered_with_uncertainty'))}."
    )


def _render_context(context_pack: list[dict[str, object]]) -> str:
    lines: list[str] = []
    for section in context_pack:
        if section.get("prompt_include") is False:
            continue
        name = str(section.get("section", "context"))
        if name == "current_user_message":
            continue
        rendered = _stringify_content(section.get("content"))
        if rendered:
            lines.append(f"[{_section_label(section, name)}] {rendered}")
    return "\n".join(lines)


def _section_label(section: dict[str, object], name: str) -> str:
    if name != "recent_turns":
        return name
    record = section.get("record")
    if not isinstance(record, dict):
        return "recent_turn"
    role = str(record.get("role", "")).casefold()
    if role not in {"assistant", "system", "user"}:
        return "recent_turn"
    return f"recent_turn role={role}"


def _stringify_content(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        return "; ".join(f"{key}={value}" for key, value in content.items() if value is not None)
    if content is None:
        return ""
    return str(content)
