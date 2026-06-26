# ruff: noqa: E501
"""Premium Streamlit Memory Command Center renderer for MIRA.

Ownership: Sarah.
Related issue: ISSUE-130.
Architecture area: UI.

One screen, tabbed. A slim header carries the brand, live status, and the
dark/light toggle; a single row of top-level tabs switches between the memory
views (Chat, Graph, Working Set, Retrieval, Reflections, Communities, Timeline).
Each view renders full-width and spacious instead of being crammed into columns.
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

TABS = (
    "💬  Chat",
    "🕸  Graph",
    "🧠  Working Set",
    "🔍  Retrieval",
    "✨  Reflections",
    "🌐  Communities",
    "🗓  Timeline",
)


def render_command_center(st: Any) -> None:
    """Render the one-screen, tabbed Memory Command Center UI."""
    _init_state(st)
    theme = _theme_control(st)
    st.markdown(command_center_css(theme), unsafe_allow_html=True)

    _render_header(st)

    tabs = st.tabs(list(TABS))
    with tabs[0]:
        _render_chat(st)
    with tabs[1]:
        _render_memory_graph(st)
    with tabs[2]:
        _render_session_working_set(st)
    with tabs[3]:
        _render_retrieval_trace(st)
    with tabs[4]:
        _render_reflections(st)
    with tabs[5]:
        _render_communities(st)
    with tabs[6]:
        _render_timeline(st)


def _unsafe(st: Any, markup: str) -> None:
    """Render an HTML fragment without Markdown treating indentation as code."""
    st.markdown(dedent(markup).strip(), unsafe_allow_html=True)


def _init_state(st: Any) -> None:
    state = st.session_state
    state.setdefault("mira_theme", "dark")
    state.setdefault("mira_last_action", "Ready")


def _theme_control(st: Any) -> str:
    state = st.session_state
    dark_mode = str(state.get("mira_theme", "dark")) != "light"
    toggle = st.toggle("Dark mode", value=dark_mode, key="mira_theme_toggle")
    state["mira_theme"] = "dark" if toggle else "light"
    return str(state["mira_theme"])


def _render_header(st: Any) -> None:
    _unsafe(
        st,
        """
        <div class="cc-header">
          <div class="brand">
            <div class="logo-mark">M</div>
            <div><h1>MIRA</h1><p class="muted">Memory Command Center</p></div>
          </div>
          <div class="header-right">
            <span class="top-pill">● MIRA 3.1 PRO</span>
            <span class="status-online"><span class="pulse"></span>ONLINE</span>
            <span class="avatar">JG</span>
          </div>
        </div>
        """,
    )


def _section_title(st: Any, title: str, subtitle: str) -> None:
    _unsafe(
        st,
        f"""
        <div class="section-title">
          <div><h2>{escape(title)}</h2><p class="muted">{escape(subtitle)}</p></div>
          <span class="badge">LIVE</span>
        </div>
        """,
    )


# ---- Views -----------------------------------------------------------------


def _render_chat(st: Any) -> None:
    _section_title(st, "Conversation", "Grounded in your durable memory")
    for message in CHAT_MESSAGES:
        _render_message(st, message["role"], message["content"])
    _render_brief(st)

    st.write("")
    action_cols = st.columns(len(ACTION_CHIPS))
    for index, chip in enumerate(ACTION_CHIPS):
        with action_cols[index]:
            if st.button(chip, key=f"action_{chip}", use_container_width=True):
                st.session_state["mira_last_action"] = chip

    composer, send = st.columns([0.88, 0.12], gap="small")
    with composer:
        st.text_input(
            "Message",
            placeholder="Ask MIRA anything about your memory...",
            label_visibility="collapsed",
            key="mira_chat_input",
        )
    with send:
        if st.button("Send", key="send_message", use_container_width=True):
            st.session_state["mira_last_action"] = "Message sent"
    st.caption(f"Last action · {st.session_state['mira_last_action']}")


def _render_message(st: Any, role: str, content: str) -> None:
    label = "You" if role == "user" else "MIRA"
    _unsafe(
        st,
        f"""
        <div class="bubble {escape(role)}">
          <small class="muted">{label}</small>
          <div>{escape(content)}</div>
        </div>
        """,
    )


def _render_brief(st: Any) -> None:
    _unsafe(
        st,
        """
        <div class="brief-card">
          <div class="brief-head">
            <div><h3>NovaDynamics Meeting Brief</h3>
            <p class="muted">Synthesized from graph paths, recent turns, and durable memory.</p></div>
            <span class="badge">27 sources</span>
          </div>
        </div>
        """,
    )
    cols = st.columns(min(4, len(BRIEF_DETAILS)) or 1)
    for index, item in enumerate(BRIEF_DETAILS):
        with cols[index % len(cols)]:
            _unsafe(
                st,
                f"""
                <div class="metric-tile">
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
            <div class="memory-row">
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
            <div class="evidence-row">
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
            <div class="reflection-card">
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
            <div class="community-row">
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
                <div class="timeline-card">
                  <small class="muted">{escape(item["when"])} · {escape(item["kind"])}</small>
                  <h4>{escape(item["title"])}</h4>
                </div>
                """,
            )
