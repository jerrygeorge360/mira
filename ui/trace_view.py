"""Answer trace page for MIRA's inspectable memory claim.

Ownership: MIRA contributors.
Related issue: ISSUE-601.
Architecture area: UI.

Renders a structured answer trace from the answer_traces repository.
"""

from __future__ import annotations

from core.db.repositories import get_answer_trace, list_answer_traces_by_session

TraceRecord = dict[str, object]


def render_trace(trace_id: str) -> str:
    """Render a single answer trace as a structured text page."""
    trace = get_answer_trace(trace_id)
    if trace is None:
        return f"Trace not found: {trace_id}"

    lines: list[str] = []
    lines.append("=" * 60)
    lines.append(f"Answer Trace: {trace['id']}")
    lines.append(f"Session: {trace['session_id']}")
    lines.append(f"Created: {trace.get('created_at', '')}")
    lines.append("=" * 60)

    _add_section(lines, "Retrieval", f"Mode: {trace.get('retrieval_mode', 'N/A')}")

    retrieved_obs = _json_list(trace.get("retrieved_observation_ids_json"))
    if retrieved_obs:
        _add_list_section(lines, "Retrieved Observations", retrieved_obs)

    retrieved_facts = _json_list(trace.get("retrieved_fact_ids_json"))
    if retrieved_facts:
        _add_list_section(lines, "Retrieved Facts", retrieved_facts)

    session_items = _json_list(trace.get("session_item_ids_json"))
    if session_items:
        _add_list_section(lines, "Session Working-Set Items", session_items)

    hot_memory = _json_list(trace.get("hot_memory_ids_json"))
    if hot_memory:
        _add_list_section(lines, "Hot Memory Items", hot_memory)

    graph_paths = _json_list(trace.get("graph_path_ids_json"))
    if graph_paths:
        _add_list_section(lines, "Graph Paths (Edges)", graph_paths)

    community_ids = _json_list(trace.get("community_summary_ids_json"))
    if community_ids:
        _add_list_section(lines, "Community Summaries", community_ids)

    hydration_ids = _json_list(trace.get("hydration_ids_json"))
    if hydration_ids:
        _add_list_section(lines, "Hydrated Session Items", hydration_ids)

    sufficiency = trace.get("sufficiency_json")
    if sufficiency is not None:
        _add_section(lines, "Sufficiency", str(sufficiency))
    else:
        _add_section(lines, "Sufficiency", "(not evaluated)")

    sections = trace.get("prompt_sections_json")
    if isinstance(sections, list) and sections:
        _add_section(lines, "Prompt Sections", "")
        for sec in sections:
            sid_text = ""
            raw_ids = sec.get("source_ids", [])
            if isinstance(raw_ids, list) and raw_ids:
                sid_text = f" ({len(raw_ids)} source IDs)"
            lines.append(f"  - {sec.get('section', '?')}{sid_text}")

    rl_id = trace.get("retrieval_log_id")
    pl_id = trace.get("prompt_log_id")
    if rl_id or pl_id:
        _add_section(lines, "Linked Logs", "")
        if rl_id:
            lines.append(f"  Retrieval Log: {rl_id}")
        if pl_id:
            lines.append(f"  Prompt Log: {pl_id}")

    lines.append("=" * 60)
    return "\n".join(lines)


def render_session_traces(session_id: str, limit: int = 10) -> str:
    """Render a list of answer traces for a session."""
    traces = list_answer_traces_by_session(session_id, limit)
    if not traces:
        return f"No traces found for session: {session_id}"

    lines: list[str] = []
    lines.append(f"Answer Traces for Session: {session_id}")
    lines.append("-" * 50)
    for trace in traces:
        mode = trace.get("retrieval_mode", "?")
        created = trace.get("created_at", "")
        lines.append(f"  {trace['id']}  |  mode={mode}  |  {created}")
    lines.append("-" * 50)
    return "\n".join(lines)


def _add_section(lines: list[str], title: str, body: str) -> None:
    lines.append("")
    lines.append(f"--- {title} ---")
    if body:
        lines.append(body)


def _add_list_section(lines: list[str], title: str, items: list[str]) -> None:
    lines.append("")
    lines.append(f"--- {title} ({len(items)}) ---")
    for item in items:
        lines.append(f"  - {item}")


def _json_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return []
