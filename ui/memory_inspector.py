"""UI contract for inspecting durable and provisional memories.

Ownership: MIRA contributors.
Related issue: ISSUE-604.
Architecture area: UI.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from core.memory.read_models import (
    list_community_summaries_read_model,
    list_foresight_read_model,
    list_reflections_read_model,
)
from core.memory.tiers import list_hot_memory_for_context
from core.session.working_set import list_active_session_items

MemorySnapshot = dict[str, list[dict[str, object]]]
SnapshotLoader = Callable[[str, int], MemorySnapshot]

SOURCE_LABELS = {
    "session_working_set": "Session Working Set",
    "hot_memory": "Hot Memory",
    "reflections": "Reflections",
    "foresight": "Foresight",
    "community_summaries": "Community Summaries",
}


def render_memory_inspector(
    session_id: str,
    st: Any | None = None,
    limit: int = 50,
    loader: SnapshotLoader | None = None,
) -> MemorySnapshot:
    """Render or return a read-only memory inspection snapshot for a session."""
    if limit < 1:
        raise ValueError("limit must be a positive integer")
    snapshot = load_memory_snapshot(session_id, limit, loader=loader)
    if st is None:
        return snapshot

    source_filter = st.sidebar.selectbox("Memory source", ["all", *SOURCE_LABELS])
    status_filter = st.sidebar.selectbox(
        "Status",
        ["all", *_distinct_field_values(snapshot, "status")],
    )
    type_filter = st.sidebar.selectbox(
        "Type",
        ["all", *_distinct_type_values(snapshot)],
    )

    filtered = filter_snapshot(snapshot, source_filter, status_filter, type_filter)
    summary = summary_rows(filtered)

    st.title("Memory Inspector")
    st.caption(
        "Read-only view of provisional session memory and durable cross-session memory records."
    )
    st.dataframe(summary)

    flattened = flatten_snapshot(filtered)
    if not flattened:
        st.info("No memory records match the selected filters.")
        return snapshot

    st.subheader("Records")
    st.dataframe([record_summary(row) for row in flattened])

    selected_id = st.selectbox("Inspect memory record", [str(row["id"]) for row in flattened])
    selected = next(row for row in flattened if str(row["id"]) == selected_id)
    st.subheader("Selected Record")
    st.markdown(record_detail_markdown(selected))

    for source, items in filtered.items():
        st.subheader(SOURCE_LABELS.get(source, source.replace("_", " ").title()))
        if items:
            st.dataframe([record_summary(_with_source(source, item)) for item in items])
        else:
            st.info(f"No {SOURCE_LABELS.get(source, source)} records.")
    return snapshot


def load_memory_snapshot(
    session_id: str,
    limit: int,
    *,
    loader: SnapshotLoader | None = None,
) -> MemorySnapshot:
    """Load memory records from existing read models."""
    if loader is not None:
        return loader(session_id, limit)
    snapshot: MemorySnapshot = {
        "session_working_set": list_active_session_items(session_id)[:limit],
        "hot_memory": list_hot_memory_for_context(session_id, "", limit),
        "reflections": list_reflections_read_model(limit),
        "foresight": list_foresight_read_model(session_id=session_id, limit=limit),
        "community_summaries": list_community_summaries_read_model(limit),
    }
    return snapshot


def filter_snapshot(
    snapshot: MemorySnapshot,
    source_filter: str = "all",
    status_filter: str = "all",
    type_filter: str = "all",
) -> MemorySnapshot:
    """Filter snapshot records by source, status, and type-like fields."""
    filtered: MemorySnapshot = {}
    for source, items in snapshot.items():
        if source_filter != "all" and source != source_filter:
            filtered[source] = []
            continue
        filtered[source] = [
            item
            for item in items
            if _matches_filter(_status(item), status_filter)
            and _matches_filter(_record_type(item), type_filter)
        ]
    return filtered


def summary_rows(snapshot: MemorySnapshot) -> list[dict[str, object]]:
    """Return source-level counts for summary display."""
    return [
        {
            "source": SOURCE_LABELS.get(source, source.replace("_", " ").title()),
            "records": len(items),
            "active": sum(
                1 for item in items if _status(item) in {"active", "provisional", "hydrated"}
            ),
            "types": ", ".join(
                sorted({_record_type(item) for item in items if _record_type(item)})
            ),
        }
        for source, items in snapshot.items()
    ]


def flatten_snapshot(snapshot: MemorySnapshot) -> list[dict[str, object]]:
    """Flatten source-keyed memory records into table-ready records."""
    rows: list[dict[str, object]] = []
    for source, items in snapshot.items():
        rows.extend(_with_source(source, item) for item in items)
    rows.sort(key=_record_sort_key)
    return rows


def record_summary(record: dict[str, object]) -> dict[str, object]:
    """Return compact columns for a memory record table."""
    return {
        "id": str(record.get("id", "")),
        "source": SOURCE_LABELS.get(str(record.get("source", "")), str(record.get("source", ""))),
        "type": _record_type(record),
        "status": _status(record),
        "priority": record.get("priority", record.get("confidence", "")),
        "content": _content(record),
    }


def record_detail_markdown(record: dict[str, object]) -> str:
    """Render one memory record as readable Markdown."""
    source = str(record.get("source", ""))
    details = [
        f"**ID:** `{record.get('id', '')}`",
        f"**Source:** {SOURCE_LABELS.get(source, source)}",
        f"**Type:** {_record_type(record) or 'unknown'}",
        f"**Status:** {_status(record) or 'unknown'}",
        f"**Content:** {_content(record) or '(empty)'}",
    ]
    evidence = record.get("source_observations") or record.get("source_observations_json")
    if evidence:
        details.append(f"**Evidence:** `{_format_value(evidence)}`")
    for key in ("scope", "priority", "confidence", "created_at", "updated_at"):
        if record.get(key) not in (None, ""):
            details.append(f"**{key.replace('_', ' ').title()}:** `{record[key]}`")
    return "\n\n".join(details)


def _with_source(source: str, item: dict[str, object]) -> dict[str, object]:
    row = dict(item)
    row["source"] = source
    return row


def _matches_filter(value: str, selected: str) -> bool:
    return selected == "all" or value == selected


def _distinct_field_values(snapshot: MemorySnapshot, field: str) -> list[str]:
    values = {
        str(item[field])
        for items in snapshot.values()
        for item in items
        if item.get(field) not in (None, "")
    }
    return sorted(values)


def _distinct_type_values(snapshot: MemorySnapshot) -> list[str]:
    values = {_record_type(item) for items in snapshot.values() for item in items}
    return sorted(value for value in values if value)


def _record_sort_key(record: dict[str, object]) -> tuple[str, str]:
    return (str(record.get("source", "")), str(record.get("id", "")))


def _record_type(record: dict[str, object]) -> str:
    for key in ("type", "memory_type", "reflection_type", "node_type"):
        if record.get(key) not in (None, ""):
            return str(record[key])
    if record.get("summary"):
        return "community_summary"
    return ""


def _status(record: dict[str, object]) -> str:
    value = record.get("status")
    return str(value) if value not in (None, "") else "active"


def _content(record: dict[str, object]) -> str:
    for key in ("content", "summary", "title", "label"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _format_value(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True)
