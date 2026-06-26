# ruff: noqa: E501
"""Claude-style Streamlit Memory Command Center renderer for MIRA.

Ownership: Sarah.
Related issue: ISSUE-130.
Architecture area: UI.

A calm, centered, single-column layout inspired by the Claude UI: warm paper
background, a coral accent, a serif greeting, plain assistant text with soft user
bubbles, and a rounded composer. Minimal text tabs switch between the memory
views (Chat, Graph, Working Set, Retrieval, Reflections, Communities, Timeline).
"""

from __future__ import annotations

from html import escape
from textwrap import dedent
from typing import Any

from ui.command_center_data import (
    ACTION_CHIPS,
    BRIEF_DETAILS,
    CHAT_MESSAGES,
    COMMUNITIES,
    EVIDENCE_ITEMS,
    GRAPH_METRICS,
    REFLECTIONS,
    SESSION_ITEMS,
    TIMELINE,
)
from ui.command_center_styles import command_center_css

VIEWS: tuple[tuple[str, str], ...] = (
    ("Chat", "💬"),
    ("Graph", "🕸"),
    ("Working Set", "🧠"),
    ("Retrieval", "🔍"),
    ("Reflections", "✨"),
    ("Communities", "🌐"),
    ("Timeline", "🗓"),
)

_RENDERERS = {
    "Chat": lambda st: _render_chat(st),
    "Graph": lambda st: _render_memory_graph(st),
    "Working Set": lambda st: _render_session_working_set(st),
    "Retrieval": lambda st: _render_retrieval_trace(st),
    "Reflections": lambda st: _render_reflections(st),
    "Communities": lambda st: _render_communities(st),
    "Timeline": lambda st: _render_timeline(st),
}


def render_command_center(st: Any) -> None:
    """Render the Claude-style UI: a left view rail plus a centered workspace."""
    _init_state(st)
    theme, active = _render_sidebar(st)
    st.markdown(command_center_css(theme), unsafe_allow_html=True)
    _RENDERERS.get(active, _RENDERERS["Chat"])(st)


def _render_sidebar(st: Any) -> tuple[str, str]:
    """Render the view rail; return (theme, active view) for this run."""
    active = str(st.session_state.get("mira_view", "Chat"))
    with st.sidebar:
        _unsafe(
            st,
            """
            <div class="brand">
              <span class="spark">✻</span>
              <span class="wordmark">MIRA</span>
            </div>
            <p class="sb-tagline">Memory Command Center</p>
            """,
        )
        for label, icon in VIEWS:
            kind = "primary" if label == active else "secondary"
            if st.button(
                f"{icon}  {label}",
                key=f"nav_{label}",
                use_container_width=True,
                type=kind,
            ):
                active = label
                st.session_state["mira_view"] = label
        _unsafe(st, '<div class="sb-divider"></div>')
        theme = _theme_control(st)
    return theme, active


def _unsafe(st: Any, markup: str) -> None:
    """Render an HTML fragment without Markdown treating indentation as code."""
    st.markdown(dedent(markup).strip(), unsafe_allow_html=True)


def _init_state(st: Any) -> None:
    state = st.session_state
    state.setdefault("mira_theme", "dark")
    state.setdefault("mira_view", "Chat")
    state.setdefault("mira_last_action", "Ready")


def _theme_control(st: Any) -> str:
    state = st.session_state
    dark_mode = str(state.get("mira_theme", "dark")) != "light"
    toggle = st.toggle("Dark mode", value=dark_mode, key="mira_theme_toggle")
    state["mira_theme"] = "dark" if toggle else "light"
    return str(state["mira_theme"])


def _section_title(st: Any, title: str, subtitle: str) -> None:
    _unsafe(
        st,
        f"""
        <div class="section-title">
          <h2>{escape(title)}</h2>
          <p class="muted">{escape(subtitle)}</p>
        </div>
        """,
    )


# ---- Views -----------------------------------------------------------------


def _render_chat(st: Any) -> None:
    _unsafe(
        st,
        """
        <div class="greeting">
          <span class="spark-lg">✻</span>
          <span>Good to see you, Jerry</span>
        </div>
        """,
    )
    for message in CHAT_MESSAGES:
        _render_message(st, message["role"], message["content"])
    _render_brief(st)

    _unsafe(st, '<p class="suggest-label">Suggested follow-ups</p>')
    chip_cols = st.columns(len(ACTION_CHIPS))
    for index, chip in enumerate(ACTION_CHIPS):
        with chip_cols[index]:
            if st.button(chip, key=f"action_{chip}", use_container_width=True):
                st.session_state["mira_last_action"] = chip

    with st.container(key="cc_composer"):
        field, send = st.columns([0.9, 0.1], gap="small", vertical_alignment="center")
        with field:
            st.text_input(
                "Message",
                placeholder="Reply to MIRA…",
                label_visibility="collapsed",
                key="mira_chat_input",
            )
        with send:
            if st.button("↑", key="send_message"):
                st.session_state["mira_last_action"] = "Message sent"
    st.caption(f"Last action · {st.session_state['mira_last_action']}")


def _render_message(st: Any, role: str, content: str) -> None:
    if role == "user":
        _unsafe(st, f'<div class="turn user"><div class="bubble">{escape(content)}</div></div>')
        return
    _unsafe(
        st,
        f"""
        <div class="turn assistant">
          <span class="spark">✻</span>
          <div class="answer">{escape(content)}</div>
        </div>
        """,
    )


def _render_brief(st: Any) -> None:
    _unsafe(
        st,
        """
        <div class="brief-card">
          <div class="brief-head">
            <h3>NovaDynamics Meeting Brief</h3>
            <span class="badge">27 sources</span>
          </div>
          <p class="muted">Synthesized from graph paths, recent turns, and durable memory.</p>
        </div>
        """,
    )
    cols = st.columns(min(4, len(BRIEF_DETAILS)) or 1)
    for index, item in enumerate(BRIEF_DETAILS):
        with cols[index % len(cols)]:
            _unsafe(
                st,
                f"""
                <div class="tile">
                  <small>{escape(item["label"])}</small>
                  <strong>{escape(item["value"])}</strong>
                </div>
                """,
            )


def _render_memory_graph(st: Any) -> None:
    _section_title(st, "Memory Graph", "Typed temporal topology")
    _unsafe(st, _graph_mock_html())
    cols = st.columns(len(GRAPH_METRICS) or 1)
    for col, metric in zip(cols, GRAPH_METRICS, strict=False):
        with col:
            st.metric(metric["label"], metric["value"])


def _graph_mock_html() -> str:
    return """
    <div class="graph-stage">
      <div class="edge e1"></div><div class="edge e2"></div>
      <div class="edge e3"></div><div class="edge e4"></div>
      <div class="node main">MIRA</div>
      <div class="node n1">You</div><div class="node n2">Docs</div>
      <div class="node n3">Tasks</div><div class="node n4">Graph</div>
    </div>
    """


def _render_session_working_set(st: Any) -> None:
    _section_title(st, "Session Working Set", "5 active items · 72% context usage")
    st.progress(72)
    for item in SESSION_ITEMS:
        _unsafe(
            st,
            f"""
            <div class="row-card">
              <div class="row-top">
                <strong>{escape(item["title"])}</strong><span class="badge">{escape(item["type"])}</span>
              </div>
              <small class="muted">{escape(item["scope"])} · {escape(item["priority"])} priority</small>
            </div>
            """,
        )


def _render_retrieval_trace(st: Any) -> None:
    _section_title(st, "Retrieval Trace", "Evidence & reasoning")
    metric_cols = st.columns(2)
    metric_cols[0].metric("Retrieved", "27")
    metric_cols[1].metric("Confidence", "94%")
    for item in EVIDENCE_ITEMS:
        _unsafe(
            st,
            f"""
            <div class="row-card">
              <div class="row-top"><span class="badge">{escape(item["rank"])}</span>
              <small class="muted">score {escape(item["score"])}</small></div>
              <strong>{escape(item["title"])}</strong>
              <div class="muted">{escape(item["source"])}</div>
            </div>
            """,
        )


def _render_reflections(st: Any) -> None:
    _section_title(st, "Reflections", "Synthesized insights")
    for item in REFLECTIONS:
        tag_values = item["tags"] if isinstance(item["tags"], list) else []
        tags = " ".join(f'<span class="chip">{escape(str(tag))}</span>' for tag in tag_values)
        _unsafe(
            st,
            f"""
            <div class="row-card">
              <small class="muted">{escape(str(item["time"]))}</small>
              <p>{escape(str(item["insight"]))}</p>
              <div class="chip-row">{tags}</div>
            </div>
            """,
        )


def _render_communities(st: Any) -> None:
    _section_title(st, "Community Summaries", "Trending clusters")
    for item in COMMUNITIES:
        _unsafe(
            st,
            f"""
            <div class="row-card">
              <div class="row-top"><strong>{escape(item["title"])}</strong>
              <span class="badge">{escape(item["delta"])}</span></div>
              <small class="muted">{escape(item["people"])} people · {escape(item["insights"])} insights</small>
            </div>
            """,
        )


def _render_timeline(st: Any) -> None:
    _section_title(st, "Timeline", "Past · Today · Future")
    cols = st.columns(min(4, len(TIMELINE)) or 1)
    for index, item in enumerate(TIMELINE):
        with cols[index % len(cols)]:
            _unsafe(
                st,
                f"""
                <div class="row-card timeline-card">
                  <small class="muted">{escape(item["when"])} · {escape(item["kind"])}</small>
                  <h4>{escape(item["title"])}</h4>
                </div>
                """,
            )
