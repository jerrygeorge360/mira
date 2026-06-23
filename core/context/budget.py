"""Prompt token budget allocation and context trimming.

Ownership: Kelechi.
Related issue: ISSUE-016.
Architecture area: context.
"""

from __future__ import annotations

Section = dict[str, object]

PROMPT_BUDGET_KEYS = (
    "system_developer_constraints",
    "current_user_message",
    "session_working_set",
    "hot_memory",
    "retrieved_memories",
    "recent_turns",
    "warm_cold_memories",
    "diagnostics",
)

SECTION_PRIORITY = {
    "system_developer_constraints": 0,
    "current_user_message": 1,
    "session_working_set": 2,
    "hot_memory": 3,
    "retrieved_memories": 4,
    "recent_turns": 5,
    "warm_cold_memories": 6,
    "diagnostics": 7,
}

BUDGET_WEIGHTS = {
    "system_developer_constraints": 16,
    "current_user_message": 14,
    "session_working_set": 18,
    "hot_memory": 14,
    "retrieved_memories": 14,
    "recent_turns": 10,
    "warm_cold_memories": 8,
    "diagnostics": 6,
}

SECTION_ALIASES = {
    "system": "system_developer_constraints",
    "developer": "system_developer_constraints",
    "constraints": "system_developer_constraints",
    "current_message": "current_user_message",
    "user": "current_user_message",
    "message": "current_user_message",
    "sws": "session_working_set",
    "session": "session_working_set",
    "session_item": "session_working_set",
    "working_set": "session_working_set",
    "cross_session_hot_memory": "hot_memory",
    "cross_session": "hot_memory",
    "hot": "hot_memory",
    "retrieved": "retrieved_memories",
    "retrieval": "retrieved_memories",
    "memory": "retrieved_memories",
    "recent": "recent_turns",
    "turn": "recent_turns",
    "turns": "recent_turns",
    "warm": "warm_cold_memories",
    "cold": "warm_cold_memories",
    "warm_cold": "warm_cold_memories",
    "diagnostic": "diagnostics",
    "trace": "diagnostics",
}


def estimate_tokens(text: str) -> int:
    """Estimate prompt tokens using a deterministic standard-library heuristic."""
    normalized = " ".join(text.split())
    if not normalized:
        return 0
    word_estimate = len(normalized.split())
    character_estimate = (len(normalized) + 3) // 4
    return max(1, word_estimate, character_estimate)


def allocate_prompt_budget(total_budget: int, response_reserve: int) -> dict[str, int]:
    """Allocate prompt budget across context sources while reserving response space."""
    if total_budget < 1:
        raise ValueError("total_budget must be a positive integer")
    if response_reserve < 0:
        raise ValueError("response_reserve must not be negative")
    if response_reserve >= total_budget:
        raise ValueError("response_reserve must be smaller than total_budget")

    available_budget = total_budget - response_reserve
    allocations = _weighted_allocations(available_budget)
    allocations["response_reserve"] = response_reserve
    allocations["prompt_budget"] = available_budget
    return allocations


def trim_context_sections(sections: list[Section], total_budget: int) -> list[Section]:
    """Return sections that fit in budget, trimming lower-priority sections first."""
    if total_budget < 0:
        raise ValueError("total_budget must not be negative")

    selected: list[tuple[int, Section]] = []
    remaining = total_budget
    ranked_sections = sorted(enumerate(sections), key=_section_sort_key)
    for index, section in ranked_sections:
        token_count = _section_token_count(section)
        if token_count <= remaining:
            selected.append((index, section))
            remaining -= token_count

    return [section for _, section in sorted(selected, key=lambda item: item[0])]


def allocate_budget(total_tokens: int) -> dict[str, int]:
    """Allocate all available tokens to prompt context for compatibility callers."""
    return allocate_prompt_budget(total_tokens, 0)


def trim_context(items: list[str], token_budget: int) -> list[str]:
    """Trim plain context strings using recent-turn priority for compatibility callers."""
    sections: list[Section] = [{"section": "recent_turns", "content": item} for item in items]
    trimmed = trim_context_sections(sections, token_budget)
    return [str(section["content"]) for section in trimmed]


def _weighted_allocations(available_budget: int) -> dict[str, int]:
    total_weight = sum(BUDGET_WEIGHTS.values())
    allocations = {
        key: available_budget * BUDGET_WEIGHTS[key] // total_weight for key in PROMPT_BUDGET_KEYS
    }
    allocated = sum(allocations.values())
    remainder = available_budget - allocated
    for key in PROMPT_BUDGET_KEYS[:remainder]:
        allocations[key] += 1
    return allocations


def _section_sort_key(indexed_section: tuple[int, Section]) -> tuple[int, float, float, int]:
    index, section = indexed_section
    return (
        SECTION_PRIORITY[_section_kind(section)],
        -_section_number(section, "priority"),
        -_section_number(section, "relevance"),
        index,
    )


def _section_kind(section: Section) -> str:
    raw_kind = (
        section.get("section")
        or section.get("kind")
        or section.get("type")
        or section.get("source")
        or section.get("name")
        or "warm_cold_memories"
    )
    normalized = str(raw_kind).strip().lower().replace("-", "_").replace(" ", "_")
    canonical = SECTION_ALIASES.get(normalized, normalized)
    if canonical not in SECTION_PRIORITY:
        return "warm_cold_memories"
    return canonical


def _section_number(section: Section, key: str) -> float:
    value = section.get(key)
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _section_token_count(section: Section) -> int:
    for key in ("tokens", "token_count", "estimated_tokens"):
        value = section.get(key)
        if isinstance(value, int):
            return max(0, value)
    return estimate_tokens(_section_text(section))


def _section_text(section: Section) -> str:
    for key in ("content", "text", "message", "value"):
        value = section.get(key)
        if isinstance(value, str):
            return value
    return ""
