"""Session Working Set inspector UI surface.

Ownership: MIRA contributors.
Related issue: ISSUE-045.
Architecture area: UI.

The Session Working Set is MIRA's most distinctive runtime layer, so this page
makes it legible: every provisional, hydrated, confirmed, or terminal item with
its full provenance (evidence span, origin, source observations) and status, plus
status/type/scope filters and a plain-language explainer of provisional vs
confirmed. It is read-only (Non-Goal: no editing). Streamlit is imported lazily
and ``st``/``loader`` are injectable so the page is testable without a UI server
or a database.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any

SessionItem = dict[str, object]
ItemLoader = Callable[[str], list[SessionItem]]

DEFAULT_SESSION_ID = "demo-session"

PROMPT_STATUSES = frozenset({"active", "confirmed", "hydrated", "provisional"})

STATUS_FILTERS: dict[str, Callable[[SessionItem], bool]] = {
    "all": lambda item: True,
    "active_only": lambda item: str(item.get("status")) in PROMPT_STATUSES,
    "provisional": lambda item: str(item.get("status")) == "provisional",
    "hydrated": lambda item: str(item.get("status")) == "hydrated",
    "rejected_expired": lambda item: str(item.get("status")) in {"rejected", "expired"},
}
STATUS_FILTER_OPTIONS = list(STATUS_FILTERS)

DISPLAY_FIELDS = (
    "content",
    "type",
    "scope",
    "status",
    "priority",
    "explicitness_label",
    "evidence_span",
    "origin",
    "source_observations",
    "resolution_reason",
)

PROVISIONAL_VS_CONFIRMED = (
    "**Provisional** items were just extracted from this session and are not yet "
    "durable. **Hydrated** items were pulled in from durable cross-session memory. "
    "**Confirmed** items passed the slow-path confirmation gate and may become "
    "durable memory. **Rejected / expired / superseded** items are retained for "
    "history but no longer injected into the prompt."
)

_MOCK_ITEMS: list[SessionItem] = [
    {
        "id": "sws_1",
        "content": "Use 2026, not 2025, for all dates.",
        "type": "correction",
        "scope": "project",
        "status": "provisional",
        "priority": 0.96,
        "explicitness_label": "direct_correction",
        "evidence_span": "Use 2026, not 2025.",
        "origin": "micro_path",
        "source_observations": ["obs_1"],
        "resolution_reason": None,
    },
    {
        "id": "sws_2",
        "content": "Keep MIRA session memory separate from durable tiers.",
        "type": "active_constraint",
        "scope": "project",
        "status": "hydrated",
        "priority": 0.8,
        "explicitness_label": "direct_instruction",
        "evidence_span": "session memory separate from durable tiers",
        "origin": "cross_session_hydration",
        "source_observations": ["obs_2"],
        "resolution_reason": None,
    },
    {
        "id": "sws_3",
        "content": "Store context in MongoDB.",
        "type": "decision",
        "scope": "project",
        "status": "rejected",
        "priority": 0.5,
        "explicitness_label": "direct_decision",
        "evidence_span": "Store context in MongoDB.",
        "origin": "micro_path",
        "source_observations": ["obs_3"],
        "resolution_reason": "Contradicted by a later correction.",
    },
]


def filter_session_items(
    items: list[SessionItem],
    status_filter: str = "all",
    item_type: str | None = None,
    scope: str | None = None,
) -> list[SessionItem]:
    """Filter items by status group, then optionally by type and scope."""
    predicate = STATUS_FILTERS.get(status_filter, STATUS_FILTERS["all"])
    filtered = [item for item in items if predicate(item)]
    if item_type and item_type != "all":
        filtered = [item for item in filtered if str(item.get("type")) == item_type]
    if scope and scope != "all":
        filtered = [item for item in filtered if str(item.get("scope")) == scope]
    return filtered


def load_session_items(session_id: str) -> list[SessionItem]:
    """Load all Session Working Set items for a session across every status."""
    from core.db.repositories import enum_values, list_session_items_by_status

    items: list[SessionItem] = []
    for status in sorted(enum_values("session_item_status")):
        for record in list_session_items_by_status(session_id, status):
            items.append(_normalize(record))
    return items


def render_session_working_set(
    session_id: str = DEFAULT_SESSION_ID,
    st: Any | None = None,
    loader: ItemLoader | None = None,
    *,
    use_mock: bool = True,
) -> None:
    """Render the read-only Session Working Set inspector page."""
    streamlit = st if st is not None else _load_streamlit()
    items = _resolve_loader(loader, use_mock)(session_id)

    streamlit.title("🧠 Session Working Set")
    streamlit.caption("Provisional, hydrated, and confirmed current-session memory.")
    streamlit.markdown(PROVISIONAL_VS_CONFIRMED)

    status_filter = streamlit.sidebar.selectbox("Status", STATUS_FILTER_OPTIONS)
    type_filter = streamlit.sidebar.selectbox("Type", ["all", *_distinct(items, "type")])
    scope_filter = streamlit.sidebar.selectbox("Scope", ["all", *_distinct(items, "scope")])

    filtered = filter_session_items(items, str(status_filter), str(type_filter), str(scope_filter))
    if not filtered:
        streamlit.info("No Session Working Set items match the current filters.")
        return

    streamlit.dataframe([_summary_row(item) for item in filtered])
    for item in filtered:
        _render_item_detail(streamlit, item)


def _render_item_detail(st: Any, item: SessionItem) -> None:
    st.subheader(f"{item.get('type', 'item')} — {item.get('status', 'unknown')}")
    st.markdown(f"**Content:** {item.get('content', '')}")
    st.markdown(f"**Evidence span:** {item.get('evidence_span') or '—'}")
    st.markdown(
        f"**Scope:** {item.get('scope', '—')} · "
        f"**Priority:** {item.get('priority', '—')} · "
        f"**Explicitness:** {item.get('explicitness_label', '—')}"
    )
    st.markdown(f"**Origin:** {item.get('origin', '—')}")
    st.markdown(f"**Source observations:** {', '.join(_source_observations(item)) or '—'}")
    resolution = item.get("resolution_reason")
    if resolution:
        st.markdown(f"**Resolution / supersession:** {resolution}")


def _summary_row(item: SessionItem) -> dict[str, object]:
    row = {field: item.get(field) for field in DISPLAY_FIELDS}
    row["source_observations"] = ", ".join(_source_observations(item))
    return row


def _resolve_loader(loader: ItemLoader | None, use_mock: bool) -> ItemLoader:
    if loader is not None:
        return loader
    if use_mock:
        return lambda _session_id: [dict(item) for item in _MOCK_ITEMS]
    return load_session_items


def _normalize(record: SessionItem) -> SessionItem:
    item = dict(record)
    if "source_observations" not in item and "source_observations_json" in item:
        item["source_observations"] = item.get("source_observations_json")
    return item


def _source_observations(item: SessionItem) -> list[str]:
    value = item.get("source_observations")
    if value is None:
        value = item.get("source_observations_json")
    if isinstance(value, list):
        return [str(entry) for entry in value]
    return []


def _distinct(items: list[SessionItem], field: str) -> list[str]:
    return sorted({str(item.get(field)) for item in items if item.get(field) is not None})


def _load_streamlit() -> Any:
    try:
        return importlib.import_module("streamlit")
    except ModuleNotFoundError as error:  # pragma: no cover - only without streamlit
        raise RuntimeError("streamlit is not installed; install it to run the MIRA UI") from error
