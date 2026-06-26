# ruff: noqa: E501
"""Premium Streamlit Memory Command Center renderer for MIRA.

Ownership: Sarah.
Related issue: ISSUE-130.
Architecture area: UI.
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
    NAV_ITEMS,
    REFLECTIONS,
    SESSION_ITEMS,
    TIMELINE,
)
from ui.command_center_styles import command_center_css

TABS = ("Graph", "Working Set", "Trace", "Reflections", "Community")
TIMELINE_TABS = ("All", "Memories", "Events", "Tasks", "Milestones")


def render_command_center(st: Any) -> None:
    """Render the one-screen, clickable Memory Command Center UI.

    Layout is built from native Streamlit columns/containers so every control is
    a real, clickable widget; cards are keyed containers (``st.container(key=...)``
    emits a ``st-key-<key>`` class) so the glass chrome in the CSS layer actually
    wraps the widgets inside it instead of rendering as an empty box.
    """
    _init_state(st)
    theme = _theme_control(st)
    st.markdown(command_center_css(theme), unsafe_allow_html=True)

    sidebar, workspace = st.columns([0.22, 0.78], gap="large")
    with sidebar:
        _render_sidebar(st)
    with workspace:
        _render_topbar(st, theme)
        main, intelligence = st.columns([0.58, 0.42], gap="large")
        with main:
            _render_chat_workspace(st)
        with intelligence:
            _render_tabbed_intelligence(st)
        _render_timeline(st)


def _unsafe(st: Any, markup: str) -> None:
    """Render small HTML fragments without Markdown treating indentation as code."""
    st.markdown(dedent(markup).strip(), unsafe_allow_html=True)


def _init_state(st: Any) -> None:
    state = st.session_state
    state.setdefault("mira_theme", "dark")
    state.setdefault("mira_nav", "Command Center")
    state.setdefault("mira_timeline_filter", "All")
    state.setdefault("mira_last_action", "Ready")


def _theme_control(st: Any) -> str:
    state = st.session_state
    dark_mode = str(state.get("mira_theme", "dark")) != "light"
    toggle = st.toggle("Dark mode", value=dark_mode, key="mira_theme_toggle")
    state["mira_theme"] = "dark" if toggle else "light"
    return str(state["mira_theme"])


def _render_sidebar(st: Any) -> None:
    with st.container(key="cc_sidebar"):
        _unsafe(
            st,
            """
            <div class="brand">
              <div class="logo-mark">M</div>
              <div><h1>MIRA</h1><p>Memory Command Center</p></div>
            </div>
            """,
        )
        for item in NAV_ITEMS:
            label = f"{item['icon']}  {item['label']}"
            if st.button(label, key=f"nav_{item['label']}", use_container_width=True):
                st.session_state["mira_nav"] = item["label"]

        _unsafe(
            st,
            """
            <div class="status-card">
              <div class="status-online"><span class="pulse"></span>MIRA ONLINE</div>
              <div class="metric-grid" style="margin-top:12px;">
                <div class="metric-tile"><small>Memories</small><strong>12.8k</strong></div>
                <div class="metric-tile"><small>Context</small><strong>72%</strong></div>
              </div>
            </div>
            """,
        )
        if st.button("⚡  Optimize Memory", key="optimize_memory", use_container_width=True):
            st.session_state["mira_last_action"] = "Memory optimization queued"
        st.caption(f"Action · {st.session_state['mira_last_action']}")


def _render_topbar(st: Any, theme: str) -> None:
    with st.container(key="cc_topbar"):
        left, center, right = st.columns([0.38, 0.38, 0.24], gap="small")
        with left:
            _unsafe(
                st,
                '<div class="top-pill">● MIRA 3.1 PRO&nbsp;&nbsp;·&nbsp;&nbsp;Personal OS</div>',
            )
        with center:
            st.text_input(
                "Search memories",
                placeholder="Search memories, people, projects...",
                label_visibility="collapsed",
                key="mira_search",
            )
        with right:
            _unsafe(
                st,
                f"""
                <div class="profile-row">
                  <span class="chip">Theme · <strong>{escape(theme.title())}</strong></span>
                  <span class="avatar">JG</span>
                </div>
                """,
            )


def _render_chat_workspace(st: Any) -> None:
    with st.container(key="cc_chat"):
        _unsafe(
            st,
            """
            <div class="chat-title">
              <div><h2>MIRA <span class="badge">PRO</span></h2>
              <p class="muted">Your Memory. Your Advantage.</p></div>
              <span class="badge">94% context certainty</span>
            </div>
            """,
        )
        for message in CHAT_MESSAGES:
            _render_message(st, message["role"], message["content"])
        _render_brief(st)
        action_cols = st.columns(len(ACTION_CHIPS))
        for index, chip in enumerate(ACTION_CHIPS):
            with action_cols[index]:
                if st.button(chip, key=f"action_{chip}", use_container_width=True):
                    st.session_state["mira_last_action"] = chip
        composer, send = st.columns([0.86, 0.14], gap="small")
        with composer:
            st.text_input(
                "Message",
                placeholder="Ask MIRA anything about your memory...",
                label_visibility="collapsed",
                key="mira_chat_input",
            )
        with send:
            if st.button("➜", key="send_message", use_container_width=True):
                st.session_state["mira_last_action"] = "Message sent"


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
    with st.container(key="cc_brief"):
        _unsafe(
            st,
            """
            <div class="brief-head">
              <div><h3>NovaDynamics Meeting Brief</h3>
              <p class="muted">Synthesized from graph paths, recent turns, and durable memory.</p></div>
              <span class="badge">27 sources</span>
            </div>
            """,
        )
        rows = [BRIEF_DETAILS[:4], BRIEF_DETAILS[4:]]
        for row in rows:
            if not row:
                continue
            cols = st.columns(len(row))
            for col, item in zip(cols, row, strict=False):
                with col:
                    _unsafe(
                        st,
                        f"""
                        <div class="metric-tile">
                          <small>{escape(item["label"])}</small>
                          <strong>{escape(item["value"])}</strong>
                        </div>
                        """,
                    )


def _render_tabbed_intelligence(st: Any) -> None:
    tabs = st.tabs(list(TABS))
    with tabs[0]:
        _render_memory_graph(st)
    with tabs[1]:
        _render_session_working_set(st)
    with tabs[2]:
        _render_retrieval_trace(st)
    with tabs[3]:
        _render_reflections(st)
    with tabs[4]:
        _render_communities(st)


def _render_memory_graph(st: Any) -> None:
    with st.container(key="cc_panel_graph"):
        _panel_title(st, "Memory Graph", "Graph topology mock")
        _unsafe(st, _graph_mock_html())
        cols = st.columns(len(GRAPH_METRICS))
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
    with st.container(key="cc_panel_working"):
        _panel_title(st, "Session Working Set", "5 active items · 72% context usage")
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
    with st.container(key="cc_panel_trace"):
        _panel_title(st, "Retrieval Trace", "Evidence & reasoning")
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
        if st.button("View full trace", key="view_trace", use_container_width=True):
            st.session_state["mira_last_action"] = "Opening full trace"


def _render_reflections(st: Any) -> None:
    with st.container(key="cc_panel_reflections"):
        _panel_title(st, "Reflections", "Synthesized insights")
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
    with st.container(key="cc_panel_community"):
        _panel_title(st, "Community Summaries", "Trending clusters")
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
    with st.container(key="cc_timeline"):
        _panel_title(st, "Timeline", "Past · Today · Future")
        timeline_tabs = st.tabs(list(TIMELINE_TABS))
        for index, tab in enumerate(TIMELINE_TABS):
            with timeline_tabs[index]:
                _render_timeline_cards(st, tab)


def _render_timeline_cards(st: Any, selected: str) -> None:
    items = [
        item
        for item in TIMELINE
        if selected == "All" or item["kind"].casefold() == selected.removesuffix("s").casefold()
    ]
    if not items:
        st.caption("No items in this lane yet.")
        return
    cols = st.columns(min(4, len(items)))
    for index, item in enumerate(items[:4]):
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


def _panel_title(st: Any, title: str, subtitle: str) -> None:
    _unsafe(
        st,
        f"""
        <div class="panel-title">
          <div><h3>{escape(title)}</h3><p class="muted">{escape(subtitle)}</p></div>
          <span class="badge">LIVE</span>
        </div>
        """,
    )
