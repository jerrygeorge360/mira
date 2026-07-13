"""Retrieval / answer trace viewer for the MIRA UI.

Ownership: MIRA contributors.
Related issue: ISSUE-047.
Architecture area: UI.

This page explains *why* an answer happened, supporting MIRA's inspectable,
evidence-grounded claim. Given a response (answer-trace) id it shows the
retrieval mode and router reason, the retrieved records (clickable to inspect),
the Session Working Set items, graph paths, community summaries, the sufficiency
result, and the prompt budget sections. Prompt-section *content* is never shown
(only section names and source-id counts) so secret system/developer prompts are
not exposed (Non-Goal). Streamlit is lazy-imported and ``st``/the loader are
injectable so the page is testable without Streamlit or a database.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any

Trace = dict[str, object]
TraceLoader = Callable[[str], "Trace | None"]

DEFAULT_TRACE_ID = "demo-trace"

SENSITIVE_SECTIONS = frozenset({"system_prompt", "developer_message", "system"})

_MOCK_TRACE: Trace = {
    "id": "demo-trace",
    "retrieval_mode": "relational",
    "router_reason": "entity-centered change question (MongoDB -> PostgreSQL)",
    "retrieved_observation_ids": ["obs_1", "obs_2"],
    "retrieved_fact_ids": ["fact_1"],
    "session_item_ids": ["sws_1"],
    "hot_memory_ids": ["wm_1"],
    "graph_path_ids": ["node_e3", "node_e2"],
    "community_summary_ids": ["comm_persistence"],
    "sufficiency": {"is_sufficient": True, "missing": [], "rewrite_query": None},
    "prompt_sections": [
        {"section": "session_working_set", "source_ids": ["sws_1"]},
        {"section": "system_prompt", "source_ids": []},
        {"section": "retrieved", "source_ids": ["obs_1", "obs_2", "fact_1"]},
    ],
    "hydration_ids": [],
}


def render_retrieval_trace(
    trace_id: str = DEFAULT_TRACE_ID,
    st: Any | None = None,
    loader: TraceLoader | None = None,
    *,
    use_mock: bool = True,
) -> None:
    """Render the answer trace for one response id."""
    streamlit = st if st is not None else _load_streamlit()
    trace = _resolve_loader(loader, use_mock)(trace_id)

    streamlit.title("🔎 Retrieval Trace")
    streamlit.caption("Why MIRA produced this answer. (System/developer prompt text is hidden.)")
    if not trace:
        streamlit.warning(f"No answer trace found for response id: {trace_id}")
        return

    streamlit.markdown(f"**Response id:** {trace.get('id', trace_id)}")
    streamlit.markdown(f"**Retrieval mode:** {trace.get('retrieval_mode', '—')}")
    streamlit.markdown(f"**Router reason:** {trace.get('router_reason') or '—'}")

    _render_sufficiency(streamlit, trace)
    _render_retrieved_records(streamlit, trace)
    _render_id_section(streamlit, "🧠 Session Working Set items", trace.get("session_item_ids"))
    _render_id_section(streamlit, "🕸️ Graph paths", trace.get("graph_path_ids"))
    _render_id_section(streamlit, "🗂️ Community summaries", trace.get("community_summary_ids"))
    _render_prompt_sections(streamlit, trace)


def _render_sufficiency(st: Any, trace: Trace) -> None:
    sufficiency = trace.get("sufficiency")
    st.subheader("Sufficiency")
    if not isinstance(sufficiency, dict):
        st.markdown("Sufficiency: — (not recorded)")
        return
    verdict = "sufficient" if sufficiency.get("is_sufficient") else "insufficient"
    missing = sufficiency.get("missing") or []
    st.markdown(f"**Result:** {verdict}")
    st.markdown(f"**Missing:** {', '.join(str(m) for m in missing) if missing else 'none'}")
    if sufficiency.get("rewrite_query"):
        st.markdown(f"**Retry query:** {sufficiency.get('rewrite_query')}")


def _render_retrieved_records(st: Any, trace: Trace) -> None:
    records = _retrieved_records(trace)
    st.subheader("Retrieved records")
    if not records:
        st.info("No records were retrieved for this answer.")
        return
    st.dataframe(records)
    selected = st.selectbox("Inspect a retrieved record", [record["id"] for record in records])
    detail = next((record for record in records if record["id"] == selected), records[0])
    st.markdown(f"**{detail['id']}** — {detail['kind']}")


def _render_id_section(st: Any, heading: str, ids: object) -> None:
    st.subheader(heading)
    values = [str(value) for value in ids] if isinstance(ids, list) else []
    if values:
        st.dataframe([{"id": value} for value in values])
    else:
        st.markdown("—")


def _render_prompt_sections(st: Any, trace: Trace) -> None:
    st.subheader("Prompt sections (budget)")
    sections = trace.get("prompt_sections")
    if not isinstance(sections, list) or not sections:
        st.markdown("—")
        return
    st.dataframe([_section_row(section) for section in sections if isinstance(section, dict)])


def _section_row(section: dict[str, object]) -> dict[str, object]:
    name = str(section.get("section", ""))
    source_ids = section.get("source_ids")
    count = len(source_ids) if isinstance(source_ids, list) else 0
    sensitive = name in SENSITIVE_SECTIONS
    return {
        "section": name,
        "source_items": count,
        "note": "content hidden (sensitive)" if sensitive else "",
    }


def _retrieved_records(trace: Trace) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for observation_id in _as_str_list(trace.get("retrieved_observation_ids")):
        records.append({"id": observation_id, "kind": "observation"})
    for fact_id in _as_str_list(trace.get("retrieved_fact_ids")):
        records.append({"id": fact_id, "kind": "atomic_fact"})
    return records


def load_trace(trace_id: str) -> Trace | None:
    """Load and normalize one answer trace from the repository (read-only)."""
    from core.db.repositories import bind_workspace, configured_workspace_context

    repository = bind_workspace(
        configured_workspace_context(
            "MIRA_STREAMLIT_WORKSPACE_ID", allow_development_fallback=False
        )
    )
    record = repository.get_answer_trace(trace_id)
    if record is None:
        return None
    return _normalize(record)


def _normalize(record: Trace) -> Trace:
    def field(name: str) -> object:
        return record[name] if name in record else record.get(f"{name}_json")

    return {
        "id": record.get("id", ""),
        "retrieval_mode": record.get("retrieval_mode", "—"),
        "router_reason": record.get("router_reason"),
        "retrieved_observation_ids": field("retrieved_observation_ids"),
        "retrieved_fact_ids": field("retrieved_fact_ids"),
        "session_item_ids": field("session_item_ids"),
        "hot_memory_ids": field("hot_memory_ids"),
        "graph_path_ids": field("graph_path_ids"),
        "community_summary_ids": field("community_summary_ids"),
        "sufficiency": field("sufficiency"),
        "prompt_sections": field("prompt_sections"),
        "hydration_ids": field("hydration_ids"),
    }


def _resolve_loader(loader: TraceLoader | None, use_mock: bool) -> TraceLoader:
    if loader is not None:
        return loader
    if use_mock:
        return lambda trace_id: dict(_MOCK_TRACE) if trace_id else None
    return load_trace


def _as_str_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _load_streamlit() -> Any:
    try:
        return importlib.import_module("streamlit")
    except ModuleNotFoundError as error:  # pragma: no cover - only without streamlit
        raise RuntimeError("streamlit is not installed; install it to run the MIRA UI") from error
