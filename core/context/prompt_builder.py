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
) -> str:
    """Render the answer-generation prompt from an existing context pack."""
    return render_prompt(
        "answer_generation",
        {
            "user_message": user_message,
            "answer_mode": answer_mode,
            "prompt_context": _render_context(context_pack),
        },
    )


def _render_context(context_pack: list[dict[str, object]]) -> str:
    lines: list[str] = []
    for section in context_pack:
        name = str(section.get("section", "context"))
        if name == "current_user_message":
            continue
        rendered = _stringify_content(section.get("content"))
        if rendered:
            lines.append(f"[{name}] {rendered}")
    return "\n".join(lines)


def _stringify_content(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        return "; ".join(f"{key}={value}" for key, value in content.items() if value is not None)
    if content is None:
        return ""
    return str(content)
