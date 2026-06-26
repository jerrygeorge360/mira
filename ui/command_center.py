# ruff: noqa: E501
"""Claude-style Streamlit Memory Command Center renderer for MIRA.

Ownership: Sarah.
Related issue: ISSUE-130.
Architecture area: UI.

The navigation rail is a real, always-visible column (not st.sidebar, whose
collapse chrome could hide the nav with no way back). It holds the brand, a new
conversation action, the view list, recents, a user footer, and the theme
toggle. The workspace renders the active view; Chat uses native st.chat_message
bubbles with an inline composer, and the Graph view embeds a real 3D graph.
"""

from __future__ import annotations

import json
from html import escape
from textwrap import dedent
from typing import Any

from ui.command_center_data import (
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

# (label, material-symbol icon name) — clean monochrome line icons, Claude-style.
_PRIMARY_VIEWS: tuple[tuple[str, str], ...] = (("Chat", "chat_bubble"),)
_MEMORY_VIEWS: tuple[tuple[str, str], ...] = (
    ("Graph", "hub"),
    ("Working Set", "layers"),
    ("Retrieval", "search"),
    ("Reflections", "auto_awesome"),
    ("Communities", "groups"),
    ("Timeline", "timeline"),
)
VIEWS: tuple[tuple[str, str], ...] = _PRIMARY_VIEWS + _MEMORY_VIEWS

_TITLES = {"Chat": "NovaDynamics meeting prep"}

_RECENTS = (
    "NovaDynamics meeting prep",
    "Q3 roadmap trade-offs",
    "Benchmark cost controls",
    "Onboarding Kelechi",
)


def render_command_center(st: Any) -> None:
    """Render the Claude-style UI: an always-visible rail plus a workspace."""
    _init_state(st)

    # The rail is pinned flush to the left screen edge via CSS (position: fixed),
    # and the workspace is centered in the remaining space — like Claude.
    active, theme = _render_rail(st)
    st.markdown(command_center_css(theme), unsafe_allow_html=True)
    with st.container(key="cc_main"):
        title = _TITLES.get(active, active)
        _unsafe(
            st,
            f"""
            <div class="topbar">
              <div class="topbar-title">{escape(title)} <span class="caret">⌄</span></div>
              <span class="plan-pill">Free plan · <b>Upgrade</b></span>
            </div>
            """,
        )
        _RENDERERS.get(active, _render_chat)(st)


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


def _nav_button(st: Any, label: str, icon: str, active: str) -> str:
    """Render one rail nav button; return the (possibly updated) active view."""
    kind = "primary" if label == active else "secondary"
    if st.button(
        f":material/{icon}:  {label}", key=f"nav_{label}", use_container_width=True, type=kind
    ):
        st.session_state["mira_view"] = label
        return label
    return active


def _render_rail(st: Any) -> tuple[str, str]:
    """Render the navigation rail; return (active view, theme) for this run."""
    active = str(st.session_state.get("mira_view", "Chat"))
    with st.container(key="cc_rail"):
        _unsafe(st, '<div class="rail-brand"><span class="wordmark">MIRA</span></div>')

        if st.button(":material/edit_square:  New chat", key="new_chat", use_container_width=True):
            st.session_state["mira_view"] = "Chat"
            active = "Chat"
        for label, icon in _PRIMARY_VIEWS:
            active = _nav_button(st, label, icon, active)

        _unsafe(st, '<p class="rail-section">Memory</p>')
        for label, icon in _MEMORY_VIEWS:
            active = _nav_button(st, label, icon, active)

        recents = "".join(f'<div class="rail-recent">{escape(t)}</div>' for t in _RECENTS)
        _unsafe(st, f'<p class="rail-section">Recents</p>{recents}')

        _unsafe(
            st,
            """
            <div class="rail-user">
              <span class="avatar">J</span>
              <div class="rail-user-meta"><strong>Jerry</strong><small>Free plan</small></div>
            </div>
            """,
        )
        theme = _theme_control(st)
    return active, theme


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


# ---- Chat ------------------------------------------------------------------


def _render_chat(st: Any) -> None:
    for message in CHAT_MESSAGES:
        _render_turn(st, str(message["role"]), str(message["content"]))
    _render_brief(st)

    with st.container(key="cc_composer"):
        add, field, send = st.columns([0.07, 0.86, 0.07], vertical_alignment="center")
        with add:
            st.button(":material/add:", key="composer_add")
        with field:
            st.text_input(
                "Message",
                placeholder="Reply to MIRA…",
                label_visibility="collapsed",
                key="mira_chat_input",
            )
        with send:
            if st.button(":material/arrow_upward:", key="send_message"):
                st.session_state["mira_last_action"] = "Message sent"
    _unsafe(
        st,
        '<p class="disclaimer">MIRA can make mistakes. Verify important details.</p>',
    )


def _render_turn(st: Any, role: str, content: str) -> None:
    if role == "user":
        _unsafe(st, f'<div class="turn user"><div class="ubub">{escape(content)}</div></div>')
        return
    _unsafe(
        st,
        f'<div class="turn bot"><div class="bot-ava">✻</div><div class="bot-msg">{escape(content)}</div></div>',
    )


def _render_brief(st: Any) -> None:
    tiles = "".join(
        f'<div class="tile"><small>{escape(item["label"])}</small><strong>{escape(item["value"])}</strong></div>'
        for item in BRIEF_DETAILS
    )
    _unsafe(
        st,
        f"""
        <div class="turn bot">
          <div class="bot-ava">✻</div>
          <div class="bot-msg bot-msg-wide">
            <div class="brief-card">
              <div class="row-top"><strong>NovaDynamics Meeting Brief</strong><span class="badge">27 sources</span></div>
              <p class="muted">Synthesized from graph paths, recent turns, and durable memory.</p>
              <div class="tile-grid">{tiles}</div>
            </div>
          </div>
        </div>
        """,
    )


# ---- Graph (3D) ------------------------------------------------------------


def _render_memory_graph(st: Any) -> None:
    _section_title(st, "Memory Graph", "Typed temporal topology · drag to rotate, scroll to zoom")
    theme = str(st.session_state.get("mira_theme", "dark"))
    st.components.v1.html(_graph_3d_html(theme), height=470)
    cols = st.columns(len(GRAPH_METRICS) or 1)
    for col, metric in zip(cols, GRAPH_METRICS, strict=False):
        with col:
            st.metric(metric["label"], metric["value"])


def _graph_data() -> dict[str, list[dict[str, object]]]:
    palette = {
        "entity": "#cc785c",
        "observation": "#5b8def",
        "reflection": "#9b7ad6",
        "community": "#3fb27f",
        "foresight": "#e0a13a",
        "atomic_fact": "#8a8f99",
    }
    raw_nodes = [
        ("mira", "MIRA", "entity", 14),
        ("you", "You", "entity", 11),
        ("nova", "NovaDynamics", "entity", 9),
        ("demo", "Final demo", "foresight", 8),
        ("bench", "Official benchmark", "foresight", 8),
        ("judge", "LLM-as-Judge", "observation", 6),
        ("budget", "Budget control", "observation", 6),
        ("refl1", "Prefers credible eval", "reflection", 7),
        ("refl2", "Cost-conscious", "reflection", 7),
        ("comm", "Evaluation cluster", "community", 10),
        ("kelechi", "Kelechi", "entity", 6),
        ("slack", "Slack bot", "observation", 5),
        ("roadmap", "Q3 roadmap", "atomic_fact", 5),
        ("sqlite", "SQLite source", "atomic_fact", 5),
    ]
    nodes = [
        {"id": nid, "name": name, "type": ntype, "val": val, "color": palette[ntype]}
        for nid, name, ntype, val in raw_nodes
    ]
    links = [
        ("you", "mira"),
        ("you", "nova"),
        ("nova", "demo"),
        ("demo", "bench"),
        ("bench", "judge"),
        ("bench", "budget"),
        ("judge", "comm"),
        ("budget", "comm"),
        ("comm", "refl1"),
        ("comm", "refl2"),
        ("refl1", "you"),
        ("refl2", "budget"),
        ("mira", "kelechi"),
        ("kelechi", "slack"),
        ("mira", "roadmap"),
        ("mira", "sqlite"),
        ("nova", "comm"),
    ]
    return {"nodes": nodes, "links": [{"source": s, "target": t} for s, t in links]}


def _graph_3d_html(theme: str) -> str:
    link_color = "rgba(45,44,40,0.28)" if theme == "light" else "rgba(236,235,229,0.22)"
    label_text = "#2d2c28" if theme == "light" else "#f3f2ec"
    data_json = json.dumps(_graph_data())
    return f"""
    <div id="mira-graph" style="width:100%;height:460px;border-radius:16px;overflow:hidden;"></div>
    <script src="https://unpkg.com/3d-force-graph@1.73.4/dist/3d-force-graph.min.js"></script>
    <script>
      (function() {{
        const data = {data_json};
        const el = document.getElementById('mira-graph');
        if (!window.ForceGraph3D) {{
          el.innerHTML = '<p style="color:{label_text};font-family:sans-serif;padding:1rem">3D graph needs internet access to load the renderer.</p>';
          return;
        }}
        const G = ForceGraph3D()(el)
          .backgroundColor('rgba(0,0,0,0)')
          .graphData(data)
          .nodeLabel(n => n.name + ' · ' + n.type)
          .nodeColor(n => n.color)
          .nodeVal(n => n.val)
          .nodeOpacity(0.95)
          .linkColor(() => '{link_color}')
          .linkWidth(0.8)
          .linkOpacity(0.5)
          .showNavInfo(false)
          .width(el.clientWidth)
          .height(460);
        G.cameraPosition({{ z: 220 }});
        window.addEventListener('resize', () => G.width(el.clientWidth));
      }})();
    </script>
    """


# ---- Other views -----------------------------------------------------------


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


_RENDERERS = {
    "Chat": _render_chat,
    "Graph": _render_memory_graph,
    "Working Set": _render_session_working_set,
    "Retrieval": _render_retrieval_trace,
    "Reflections": _render_reflections,
    "Communities": _render_communities,
    "Timeline": _render_timeline,
}
