"""Context merger for prompt-ready runtime context packs.

Ownership: Jerry.
Related issue: ISSUE-017.
Architecture area: context.
"""

from __future__ import annotations

from collections.abc import Iterable

ContextRecord = dict[str, object]

SECTION_ORDER = {
    "current_user_message": 0,
    "session_working_set": 1,
    "durable_memory": 2,
    "retrieved_records": 3,
    "recent_turns": 4,
    "ambient_context": 5,
    "diagnostics": 6,
}

SOURCE_RANK = {
    "session_working_set": 0,
    "durable_memory": 1,
    "retrieved_records": 2,
    "recent_turns": 3,
    "ambient_context": 4,
    "current_user_message": 5,
    "diagnostics": 6,
}

SUPPORTED_CORRECTION_TYPES = frozenset({"correction", "active_constraint", "decision"})


def merge_context_sources(
    current_message: str,
    recent_turns: list[ContextRecord],
    session_items: list[ContextRecord],
    durable_memory_items: list[ContextRecord],
    ambient_context: dict[str, object],
    retrieved_items: list[ContextRecord],
) -> list[ContextRecord]:
    """Merge runtime context sources into a prompt-builder-ready context pack."""
    context_pack: list[ContextRecord] = []
    conflict_log: list[ContextRecord] = []

    context_pack.append(_current_message_section(current_message))
    context_pack.extend(_source_sections("session_working_set", session_items))
    context_pack.extend(_source_sections("durable_memory", durable_memory_items))
    context_pack.extend(_source_sections("retrieved_records", retrieved_items))
    context_pack.extend(_recent_turn_sections(recent_turns))
    if ambient_context:
        context_pack.append(
            {
                "section": "ambient_context",
                "content": dict(ambient_context),
                "source_ids": _source_ids(ambient_context),
                "priority": _priority(ambient_context),
                "supported": bool(ambient_context),
                "conflicts": [],
            }
        )

    deduplicated = _merge_duplicates(context_pack)
    _apply_session_conflict_rules(deduplicated, conflict_log)
    if conflict_log:
        deduplicated.append(
            {
                "section": "diagnostics",
                "content": "Context conflicts detected for slow-path review.",
                "source_ids": [],
                "priority": 0.0,
                "supported": True,
                "conflicts": conflict_log,
            }
        )
    return sorted(deduplicated, key=_context_sort_key)


def merge_context(
    recent_turns: list[str],
    session_items: list[ContextRecord],
    retrieved_memories: list[ContextRecord],
    ambient_context: dict[str, object],
) -> list[ContextRecord]:
    """Merge legacy context inputs for compatibility callers."""
    turn_records: list[ContextRecord] = [{"content": turn} for turn in recent_turns]
    return merge_context_sources(
        current_message="",
        recent_turns=turn_records,
        session_items=session_items,
        durable_memory_items=[],
        ambient_context=ambient_context,
        retrieved_items=retrieved_memories,
    )


def _current_message_section(current_message: str) -> ContextRecord:
    return {
        "section": "current_user_message",
        "content": current_message,
        "source_ids": [],
        "priority": 1.0,
        "supported": True,
        "conflicts": [],
    }


def _source_sections(source: str, items: Iterable[ContextRecord]) -> list[ContextRecord]:
    return [_to_context_section(source, item) for item in items]


def _recent_turn_sections(recent_turns: Iterable[ContextRecord]) -> list[ContextRecord]:
    return [_to_context_section("recent_turns", turn) for turn in recent_turns]


def _to_context_section(section: str, item: ContextRecord) -> ContextRecord:
    return {
        "section": section,
        "content": item.get("content") or _fallback_content(item),
        "source_ids": _source_ids(item),
        "priority": _priority(item),
        "supported": _is_supported(item),
        "record": dict(item),
        "conflicts": [],
    }


def _merge_duplicates(records: list[ContextRecord]) -> list[ContextRecord]:
    merged: list[ContextRecord] = []
    by_key: dict[tuple[str, str], ContextRecord] = {}
    for record in records:
        key = _dedupe_key(record)
        if key is None:
            merged.append(record)
            continue
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = record
            merged.append(record)
            continue
        _merge_record(existing, record)
    return merged


def _merge_record(existing: ContextRecord, incoming: ContextRecord) -> None:
    existing["source_ids"] = sorted(
        set(_string_list(existing.get("source_ids")))
        | set(_string_list(incoming.get("source_ids")))
    )
    existing["priority"] = max(_priority(existing), _priority(incoming))
    existing["supported"] = bool(existing.get("supported")) or bool(incoming.get("supported"))
    sections = set(_string_list(existing.get("merged_sections")))
    sections.add(str(existing["section"]))
    sections.add(str(incoming["section"]))
    existing["merged_sections"] = sorted(sections)
    if _source_rank(str(incoming["section"])) < _source_rank(str(existing["section"])):
        existing["section"] = incoming["section"]
        existing["content"] = incoming["content"]
        existing["record"] = incoming.get("record", incoming)


def _apply_session_conflict_rules(
    records: list[ContextRecord],
    conflict_log: list[ContextRecord],
) -> None:
    session_records = [record for record in records if record["section"] == "session_working_set"]
    durable_records = [record for record in records if record["section"] == "durable_memory"]
    retrieved_records = [record for record in records if record["section"] == "retrieved_records"]
    for session_record in session_records:
        if not _is_session_override(session_record):
            continue
        for other_record in (*durable_records, *retrieved_records):
            if not _records_conflict(session_record, other_record):
                continue
            session_record["prompt_winner"] = True
            other_record["shadowed_by_session"] = True
            other_record["prompt_include"] = False
            conflict = {
                "type": "session_override",
                "winner_source_ids": session_record["source_ids"],
                "shadowed_source_ids": other_record["source_ids"],
                "winner_content": session_record["content"],
                "shadowed_content": other_record["content"],
                "slow_path_action": "review_for_SUPERSEDED_BY_or_CONTRADICTS",
            }
            session_record["conflicts"] = [*_conflicts(session_record), conflict]
            other_record["conflicts"] = [*_conflicts(other_record), conflict]
            conflict_log.append(conflict)


def _is_session_override(record: ContextRecord) -> bool:
    item_type = _record_field(record, "type")
    status = _record_field(record, "status")
    return item_type in SUPPORTED_CORRECTION_TYPES and status not in {
        "expired",
        "rejected",
        "resolved",
        "superseded",
    }


def _conflicts(record: ContextRecord) -> list[ContextRecord]:
    value = record.get("conflicts", [])
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _records_conflict(left: ContextRecord, right: ContextRecord) -> bool:
    if _source_overlap(left, right):
        return False
    left_tokens = _meaningful_tokens(str(left.get("content", "")))
    right_tokens = _meaningful_tokens(str(right.get("content", "")))
    if not left_tokens or not right_tokens:
        return False
    if left_tokens & right_tokens:
        return _has_negation_difference(str(left["content"]), str(right["content"]))
    return False


def _source_overlap(left: ContextRecord, right: ContextRecord) -> bool:
    return bool(
        set(_string_list(left.get("source_ids"))) & set(_string_list(right.get("source_ids")))
    )


def _has_negation_difference(left: str, right: str) -> bool:
    negation_markers = ("not", "don't", "do not", "never", "instead", "rather than")
    left_normalized = _normalize(left)
    right_normalized = _normalize(right)
    return any(marker in left_normalized for marker in negation_markers) != any(
        marker in right_normalized for marker in negation_markers
    )


def _dedupe_key(record: ContextRecord) -> tuple[str, str] | None:
    nested = record.get("record")
    if isinstance(nested, dict):
        primary_id = _primary_source_id(nested)
        if primary_id is not None:
            return "primary_id", primary_id
    source_ids = _string_list(record.get("source_ids"))
    if source_ids:
        return "source_ids", "|".join(sorted(source_ids))
    content = _normalize(str(record.get("content", "")))
    if content:
        return "content", content
    return None


def _context_sort_key(record: ContextRecord) -> tuple[int, int, float, int]:
    return (
        SECTION_ORDER.get(str(record["section"]), 99),
        0 if bool(record.get("supported")) else 1,
        -_priority(record),
        0 if bool(record.get("prompt_include", True)) else 1,
    )


def _source_ids(item: dict[str, object]) -> list[str]:
    values: list[str] = []
    primary_id = _primary_source_id(item)
    if primary_id is not None:
        values.append(primary_id)
    for key in ("source_ids", "source_observations", "included_ids"):
        value = item.get(key)
        values.extend(_string_list(value))
    return sorted(dict.fromkeys(values))


def _primary_source_id(item: dict[str, object]) -> str | None:
    for key in ("id", "source_id", "source_record_id", "observation_id"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _priority(item: dict[str, object]) -> float:
    value = item.get("priority", item.get("score", item.get("relevance", 0.0)))
    if value == 0.0:
        nested = item.get("record")
        if isinstance(nested, dict):
            value = nested.get("priority", nested.get("score", nested.get("relevance", 0.0)))
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _is_supported(item: dict[str, object]) -> bool:
    if "supported" in item:
        return bool(item["supported"])
    return bool(_source_ids(item) or item.get("evidence_span"))


def _record_field(record: ContextRecord, key: str) -> str:
    nested = record.get("record")
    if isinstance(nested, dict):
        value = nested.get(key)
        if value is not None:
            return str(value)
    value = record.get(key)
    return "" if value is None else str(value)


def _source_rank(section: str) -> int:
    return SOURCE_RANK.get(section, 99)


def _fallback_content(item: ContextRecord) -> str:
    for key in ("summary", "text", "message", "value"):
        value = item.get(key)
        if isinstance(value, str):
            return value
    return ""


def _meaningful_tokens(value: str) -> set[str]:
    stopwords = {"a", "an", "and", "for", "is", "it", "of", "the", "to", "use"}
    return {
        token for token in _normalize(value).split() if len(token) > 2 and token not in stopwords
    }


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _normalize(value: str) -> str:
    return " ".join(value.casefold().replace(".", " ").replace(",", " ").split())
