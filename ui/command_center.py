# ruff: noqa: E501
"""Claude-style Streamlit Memory Command Center renderer for MIRA.

Ownership: MIRA contributors.
Related issue: ISSUE-130.
Architecture area: UI.

The navigation rail is a real, always-visible column (not st.sidebar, whose
collapse chrome could hide the nav with no way back). It holds the brand, a new
conversation action, the view list, recents, a user footer, and the theme
toggle. The workspace renders the active view; Chat uses native st.chat_message
bubbles with an inline composer, and the Graph view embeds a real 3D graph.
"""

from __future__ import annotations

import importlib
import json
from html import escape
from textwrap import dedent
from typing import Any

from ui.chat import DEFAULT_SESSION_ID, MockChatAgent
from ui.command_center_data import (
    BRIEF_DETAILS,
    CHAT_MESSAGES,
    COMMUNITIES,
    EVIDENCE_ITEMS,
    GRAPH_METRICS,
    REFLECTIONS,
    RESULT_ABSTRACT,
    RESULT_CASES,
    RESULT_CAVEATS,
    RESULT_EVIDENCE,
    RESULT_FIXES,
    RESULT_STATS,
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
    ("Results", "verified"),
)
VIEWS: tuple[tuple[str, str], ...] = _PRIMARY_VIEWS + _MEMORY_VIEWS

_TITLES = {"Chat": "Chat"}

_HISTORY_THREADS: tuple[dict[str, object], ...] = (
    {
        "id": "nova",
        "title": "NovaDynamics meeting prep",
        "subtitle": "27 memories · relational",
        "messages": CHAT_MESSAGES,
    },
    {
        "id": "roadmap",
        "title": "Q3 roadmap trade-offs",
        "subtitle": "12 memories · deep",
        "messages": [
            {"role": "user", "content": "What are the biggest Q3 roadmap trade-offs?"},
            {
                "role": "assistant",
                "content": (
                    "The main trade-off is demo polish versus backend depth. The graph, "
                    "retrieval trace, and ablation story carry the strongest judge signal."
                ),
            },
        ],
    },
    {
        "id": "benchmarks",
        "title": "Benchmark cost controls",
        "subtitle": "8 memories · quick",
        "messages": [
            {"role": "user", "content": "Keep the benchmark run credible but cheap."},
            {
                "role": "assistant",
                "content": (
                    "Use a small representative suite first: official benchmark tracks "
                    "separate from ablations, with result slots marked pending until real runs."
                ),
            },
        ],
    },
    {
        "id": "kelechi",
        "title": "Onboarding Kelechi",
        "subtitle": "5 memories · session",
        "messages": [
            {"role": "user", "content": "What should Kelechi own next?"},
            {
                "role": "assistant",
                "content": (
                    "Kelechi should stay close to infra boundaries: queue reliability, "
                    "worker runtime, CI, Docker, and repository contracts."
                ),
            },
        ],
    },
)

_CC_MESSAGES_KEY = "mira_cc_chat_messages"
_CC_USE_REAL_AGENT_KEY = "mira_cc_use_real_agent"
_CC_AGENT_STATUS_KEY = "mira_cc_agent_status"
_CC_ACTIVE_THREAD_KEY = "mira_cc_active_thread"
_CC_THREAD_TITLE_KEY = "mira_cc_thread_title"
_CC_RAIL_COLLAPSED_KEY = "mira_cc_rail_collapsed"


def render_command_center(st: Any) -> None:
    """Render the Claude-style UI: an always-visible rail plus a workspace."""
    _init_state(st)

    theme = str(st.session_state.get("mira_theme", "dark"))
    rail_collapsed = bool(st.session_state.get(_CC_RAIL_COLLAPSED_KEY, False))
    st.markdown(command_center_css(theme, rail_collapsed=rail_collapsed), unsafe_allow_html=True)
    active, theme = _render_rail(st)
    with st.container(key="cc_main"):
        title = _TITLES.get(active, active)
        if active == "Chat":
            title = str(st.session_state.get(_CC_THREAD_TITLE_KEY, title))
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
    state.setdefault(_CC_ACTIVE_THREAD_KEY, "nova")
    state.setdefault(_CC_THREAD_TITLE_KEY, "NovaDynamics meeting prep")
    state.setdefault(_CC_MESSAGES_KEY, _seed_messages("nova"))
    state.setdefault(_CC_USE_REAL_AGENT_KEY, False)
    state.setdefault(_CC_AGENT_STATUS_KEY, "Demo data")
    state.setdefault(_CC_RAIL_COLLAPSED_KEY, False)


def _theme_control(st: Any) -> str:
    state = st.session_state
    dark_mode = str(state.get("mira_theme", "dark")) != "light"
    toggle = st.toggle("Dark mode", value=dark_mode, key="mira_theme_toggle")
    state["mira_theme"] = "dark" if toggle else "light"
    return str(state["mira_theme"])


def _toggle_theme(st: Any) -> None:
    """Toggle the command-center theme from icon-only collapsed rail mode."""
    current = str(st.session_state.get("mira_theme", "dark"))
    st.session_state["mira_theme"] = "light" if current == "dark" else "dark"


def _go_home(st: Any) -> None:
    """on_click callback: return to the landing page on the next run."""
    st.session_state["mira_entered"] = False


def _select_view(st: Any, label: str) -> None:
    """on_click callback: set the active view before the script reruns.

    Running in the callback (not after st.button returns) means the new value is
    in place before any nav button renders, so every button's active highlight is
    correct on the same run instead of lagging one click behind.
    """
    st.session_state["mira_view"] = label


def _toggle_rail(st: Any) -> None:
    """Collapse or expand the command-center rail."""
    st.session_state[_CC_RAIL_COLLAPSED_KEY] = not bool(
        st.session_state.get(_CC_RAIL_COLLAPSED_KEY, False)
    )


def _start_new_chat(st: Any) -> None:
    """Create a clean command-center chat thread."""
    st.session_state["mira_view"] = "Chat"
    st.session_state[_CC_ACTIVE_THREAD_KEY] = "new"
    st.session_state[_CC_THREAD_TITLE_KEY] = "New conversation"
    st.session_state[_CC_MESSAGES_KEY] = []
    st.session_state[_CC_AGENT_STATUS_KEY] = "Ready"


def _select_history_thread(st: Any, thread_id: str) -> None:
    """Load one saved/demo history item into the chat workspace."""
    thread = _history_thread(thread_id)
    st.session_state["mira_view"] = "Chat"
    st.session_state[_CC_ACTIVE_THREAD_KEY] = thread_id
    st.session_state[_CC_THREAD_TITLE_KEY] = str(thread["title"])
    st.session_state[_CC_MESSAGES_KEY] = _copy_messages(thread.get("messages"))
    st.session_state[_CC_AGENT_STATUS_KEY] = str(thread["subtitle"])


def _nav_button(st: Any, label: str, icon: str, active: str) -> None:
    """Render one rail nav button with correct same-run active highlighting."""
    kind = "primary" if label == active else "secondary"
    st.button(
        f":material/{icon}:  {label}",
        key=f"nav_{label}",
        use_container_width=True,
        type=kind,
        on_click=_select_view,
        args=(st, label),
    )


def _render_rail(st: Any) -> tuple[str, str]:
    """Render the navigation rail; return (active view, theme) for this run."""
    active = str(st.session_state.get("mira_view", "Chat"))
    collapsed = bool(st.session_state.get(_CC_RAIL_COLLAPSED_KEY, False))
    with st.container(key="cc_rail"):
        if collapsed:
            st.button(
                ":material/side_navigation:",
                key="rail_expand",
                help="Open sidebar",
                use_container_width=True,
                on_click=_toggle_rail,
                args=(st,),
            )
            st.button(
                "✻",
                key="home_brand_collapsed",
                help="MIRA home",
                use_container_width=True,
                on_click=_go_home,
                args=(st,),
            )
            for label, icon in _PRIMARY_VIEWS + _MEMORY_VIEWS:
                st.button(
                    f":material/{icon}:",
                    key=f"nav_collapsed_{_key_slug(label)}",
                    help=label,
                    use_container_width=True,
                    type="primary" if label == active else "secondary",
                    on_click=_select_view,
                    args=(st, label),
                )
            current_theme = str(st.session_state.get("mira_theme", "dark"))
            st.button(
                ":material/light_mode:" if current_theme == "dark" else ":material/dark_mode:",
                key="rail_theme_icon",
                help="Toggle theme",
                use_container_width=True,
                on_click=_toggle_theme,
                args=(st,),
            )
            return active, str(st.session_state.get("mira_theme", "dark"))

        rail_top_l, rail_top_r = st.columns([0.76, 0.24], vertical_alignment="center")
        with rail_top_l:
            st.button(
                "✻ MIRA",
                key="home_brand",
                use_container_width=True,
                on_click=_go_home,
                args=(st,),
            )
        with rail_top_r:
            st.button(
                ":material/left_panel_close:",
                key="rail_collapse",
                help="Close sidebar",
                use_container_width=True,
                on_click=_toggle_rail,
                args=(st,),
            )

        st.button(
            ":material/edit_square:  New chat",
            key="new_chat",
            use_container_width=True,
            on_click=_start_new_chat,
            args=(st,),
        )
        for label, icon in _PRIMARY_VIEWS:
            _nav_button(st, label, icon, active)

        _unsafe(st, '<p class="rail-section">Memory</p>')
        for label, icon in _MEMORY_VIEWS:
            _nav_button(st, label, icon, active)

        _unsafe(st, '<p class="rail-section">History</p>')
        active_thread = str(st.session_state.get(_CC_ACTIVE_THREAD_KEY, "nova"))
        for thread in _HISTORY_THREADS:
            thread_id = str(thread["id"])
            prefix = "●" if thread_id == active_thread else "○"
            st.button(
                f"{prefix}  {thread['title']}\n\n{thread['subtitle']}",
                key=f"history_{thread_id}",
                use_container_width=True,
                type="primary" if thread_id == active_thread else "secondary",
                on_click=_select_history_thread,
                args=(st, thread_id),
            )

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


def _history_thread(thread_id: str) -> dict[str, object]:
    for thread in _HISTORY_THREADS:
        if thread["id"] == thread_id:
            return thread
    return _HISTORY_THREADS[0]


def _key_slug(value: str) -> str:
    """Return a small stable fragment for Streamlit widget keys."""
    return value.replace(" ", "_")


def _seed_messages(thread_id: str) -> list[dict[str, object]]:
    return _copy_messages(_history_thread(thread_id).get("messages"))


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
    use_real_agent = st.toggle(
        "Use real MIRA agent",
        value=bool(st.session_state.get(_CC_USE_REAL_AGENT_KEY, False)),
        key=_CC_USE_REAL_AGENT_KEY,
        help=(
            "Off uses deterministic demo data. On calls core.agent.Agent for actual "
            "MIRA runtime behavior."
        ),
    )
    mode = "Real backend" if use_real_agent else "Demo data"
    _unsafe(
        st,
        f"""
        <div class="chat-mode-row">
          <span class="badge">{escape(mode)}</span>
          <small class="muted">{escape(str(st.session_state.get(_CC_AGENT_STATUS_KEY, "Ready")))}</small>
        </div>
        """,
    )

    for message in _chat_messages(st):
        _render_turn(st, str(message["role"]), str(message["content"]))
    active_thread = str(st.session_state.get(_CC_ACTIVE_THREAD_KEY, "nova"))
    if active_thread == "nova":
        _render_brief(st)
    elif _chat_messages(st):
        _render_history_context(st)
    else:
        _render_empty_chat(st)

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
                _send_chat_message(st, use_real_agent)
    _unsafe(
        st,
        '<p class="disclaimer">MIRA can make mistakes. Verify important details.</p>',
    )


def _chat_messages(st: Any) -> list[dict[str, object]]:
    messages = st.session_state.get(_CC_MESSAGES_KEY)
    if isinstance(messages, list):
        normalized = _copy_messages(messages)
        st.session_state[_CC_MESSAGES_KEY] = normalized
        return normalized
    seeded = _copy_messages(CHAT_MESSAGES)
    st.session_state[_CC_MESSAGES_KEY] = seeded
    return seeded


def _copy_messages(value: object) -> list[dict[str, object]]:
    """Return a defensive list of chat message dictionaries."""
    if not isinstance(value, list):
        return []
    return [dict(message) for message in value if isinstance(message, dict)]


def _send_chat_message(st: Any, use_real_agent: bool) -> None:
    message = str(st.session_state.get("mira_chat_input", "")).strip()
    if not message:
        st.session_state[_CC_AGENT_STATUS_KEY] = "Write a message first"
        return

    messages = _chat_messages(st)
    messages.append({"role": "user", "content": message})
    response = _respond_to_chat(message, use_real_agent)
    messages.append({"role": "assistant", "content": str(response["answer"])})
    st.session_state[_CC_AGENT_STATUS_KEY] = str(response["status"])
    st.session_state["mira_last_action"] = "Message sent"


def _respond_to_chat(user_message: str, use_real_agent: bool) -> dict[str, object]:
    if not use_real_agent:
        response = MockChatAgent().respond(user_message)
        return {
            "answer": response.get("answer", "Demo response unavailable."),
            "status": f"Demo response · {response.get('retrieval_mode', 'quick')} retrieval",
        }

    try:
        agent_module = importlib.import_module("core.agent")
        agent = agent_module.Agent(DEFAULT_SESSION_ID)
        response = agent.respond(user_message)
    except Exception as error:  # pragma: no cover - depends on local runtime config
        return {
            "answer": (
                "I tried to use the real MIRA runtime, but it is not ready for this "
                f"turn yet: {error}"
            ),
            "status": "Real backend error",
        }
    return {
        "answer": response.get("answer", "Real agent returned no answer."),
        "status": f"Real backend · {response.get('retrieval_mode', 'unknown')} retrieval",
    }


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


def _render_history_context(st: Any) -> None:
    title = str(st.session_state.get(_CC_THREAD_TITLE_KEY, "Conversation"))
    status = str(st.session_state.get(_CC_AGENT_STATUS_KEY, "Loaded from history"))
    _unsafe(
        st,
        f"""
        <div class="turn bot">
          <div class="bot-ava">✻</div>
          <div class="bot-msg bot-msg-wide">
            <div class="brief-card">
              <div class="row-top"><strong>{escape(title)}</strong><span class="badge">History</span></div>
              <p class="muted">Loaded conversation context · {escape(status)}</p>
            </div>
          </div>
        </div>
        """,
    )


def _render_empty_chat(st: Any) -> None:
    _unsafe(
        st,
        """
        <div class="empty-chat-card">
          <strong>Start a new MIRA conversation</strong>
          <p>Use demo mode for safe UI testing, or switch on the real agent when the backend is configured.</p>
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
        (
            "mira",
            "MIRA",
            "entity",
            14,
            "Memory-Integrated Reasoning Architecture",
            "Central project entity tying observations, facts, graph edges, reflections, and retrieval behavior together.",
            "High-confidence project context",
            ["obs_001", "fact_arch_001", "graph_node_mira"],
        ),
        (
            "you",
            "You",
            "entity",
            11,
            "Primary user / project owner",
            "Used to connect preferences, corrections, assignments, and demo intent back to Jerry.",
            "Active session identity",
            ["obs_002", "entity_jerry"],
        ),
        (
            "nova",
            "NovaDynamics",
            "entity",
            9,
            "Demo customer context",
            "Example organization used to show meeting prep, retrieval traces, and source-backed synthesis.",
            "Mock demo data",
            ["obs_010", "demo_seed_nova"],
        ),
        (
            "demo",
            "Final demo",
            "foresight",
            8,
            "Future-relevant event",
            "Foresight record that should activate when demo preparation or deadlines become relevant.",
            "Pending activation",
            ["foresight_001", "obs_018"],
        ),
        (
            "bench",
            "Official benchmark",
            "foresight",
            8,
            "Evaluation milestone",
            "Tracks planned benchmark reporting separately from internal ablation studies.",
            "Result pending",
            ["eval_plan_001", "obs_022"],
        ),
        (
            "judge",
            "LLM-as-Judge",
            "observation",
            6,
            "Evaluation method observation",
            "Represents judge-based scoring for synthesis quality and answer faithfulness.",
            "Needs calibration",
            ["obs_024"],
        ),
        (
            "budget",
            "Budget control",
            "observation",
            6,
            "Prompt/context budget signal",
            "Connects context allocation, retrieval volume, and answer reliability.",
            "Runtime constraint",
            ["obs_031"],
        ),
        (
            "refl1",
            "Prefers credible eval",
            "reflection",
            7,
            "Gated reflection",
            "Higher-order pattern: Jerry wants claims backed by benchmarks, ablations, and evidence.",
            "Evidence-backed insight",
            ["reflection_004", "obs_040", "obs_041"],
        ),
        (
            "refl2",
            "Cost-conscious",
            "reflection",
            7,
            "Gated reflection",
            "Represents preference for useful memory without uncontrolled token or infrastructure cost.",
            "Evidence-backed insight",
            ["reflection_006", "obs_045"],
        ),
        (
            "comm",
            "Evaluation cluster",
            "community",
            10,
            "Community summary",
            "Cluster linking benchmarks, ablations, judge scoring, retrieval traces, and demo credibility.",
            "Deep Mode context",
            ["community_eval_001"],
        ),
        (
            "kelechi",
            "Kelechi",
            "entity",
            6,
            "Team member entity",
            "Used in ownership/review paths for infrastructure and database issues.",
            "Collaborator context",
            ["entity_kelechi", "obs_052"],
        ),
        (
            "slack",
            "Slack bot",
            "observation",
            5,
            "Integration observation",
            "Represents external surface area for bot/runtime interaction.",
            "Future integration",
            ["obs_060"],
        ),
        (
            "roadmap",
            "Q3 roadmap",
            "atomic_fact",
            5,
            "Atomic fact",
            "A structured fact candidate that can be retrieved directly or connected through the graph.",
            "Source-backed fact",
            ["fact_roadmap_001", "obs_065"],
        ),
        (
            "sqlite",
            "SQLite source",
            "atomic_fact",
            5,
            "Atomic fact",
            "SQLite is treated as source of truth while vector stores remain indexes.",
            "Accepted architecture decision",
            ["adr_0003", "fact_sqlite_001"],
        ),
    ]
    nodes = [
        {
            "id": nid,
            "name": name,
            "type": ntype,
            "val": val,
            "color": palette[ntype],
            "headline": headline,
            "summary": summary,
            "status": status,
            "evidence": evidence,
        }
        for nid, name, ntype, val, headline, summary, status, evidence in raw_nodes
    ]
    links = [
        ("you", "mira", "WORKS_ON"),
        ("you", "nova", "MENTIONS"),
        ("nova", "demo", "LEADS_TO"),
        ("demo", "bench", "LEADS_TO"),
        ("bench", "judge", "EVALUATED_BY"),
        ("bench", "budget", "CONSTRAINED_BY"),
        ("judge", "comm", "PART_OF_COMMUNITY"),
        ("budget", "comm", "PART_OF_COMMUNITY"),
        ("comm", "refl1", "DERIVED_FROM"),
        ("comm", "refl2", "DERIVED_FROM"),
        ("refl1", "you", "DESCRIBES"),
        ("refl2", "budget", "DESCRIBES"),
        ("mira", "kelechi", "OWNED_WITH"),
        ("kelechi", "slack", "IMPLEMENTS"),
        ("mira", "roadmap", "HAS_FACT"),
        ("mira", "sqlite", "HAS_FACT"),
        ("nova", "comm", "PART_OF_COMMUNITY"),
    ]
    return {
        "nodes": nodes,
        "links": [{"source": s, "target": t, "type": edge_type} for s, t, edge_type in links],
    }


def _graph_3d_html(theme: str) -> str:
    link_color = "rgba(45,44,40,0.28)" if theme == "light" else "rgba(236,235,229,0.22)"
    label_text = "#2d2c28" if theme == "light" else "#f3f2ec"
    surface = "rgba(255,255,255,0.92)" if theme == "light" else "rgba(31,30,29,0.92)"
    border = "rgba(45,44,40,0.14)" if theme == "light" else "rgba(236,235,229,0.14)"
    muted = "#777268" if theme == "light" else "#a6a197"
    accent = "#cc785c" if theme == "light" else "#d97757"
    data_json = json.dumps(_graph_data())
    return f"""
    <style>
      #mira-graph-shell {{
        position: relative;
        width: 100%;
        height: 460px;
        border-radius: 16px;
        overflow: hidden;
      }}
      #mira-graph {{
        width: 100%;
        height: 460px;
      }}
      #mira-node-panel {{
        position: absolute;
        top: 18px;
        right: 18px;
        width: min(360px, calc(100% - 36px));
        max-height: 424px;
        overflow: auto;
        padding: 16px;
        border: 1px solid {border};
        border-radius: 18px;
        background: {surface};
        color: {label_text};
        font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        box-shadow: 0 20px 60px rgba(0,0,0,.22);
        backdrop-filter: blur(18px);
      }}
      #mira-node-panel.empty {{
        opacity: .82;
      }}
      .node-kicker {{
        color: {accent};
        font-size: 11px;
        font-weight: 800;
        letter-spacing: .08em;
        text-transform: uppercase;
      }}
      .node-title {{
        margin: 6px 0 4px;
        font-size: 20px;
        font-weight: 850;
        letter-spacing: -.02em;
      }}
      .node-headline {{
        color: {muted};
        font-size: 13px;
        line-height: 1.45;
      }}
      .node-summary {{
        margin: 14px 0;
        font-size: 13px;
        line-height: 1.55;
      }}
      .node-pill-row {{
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin: 12px 0;
      }}
      .node-pill {{
        border: 1px solid {border};
        border-radius: 999px;
        padding: 5px 9px;
        color: {muted};
        font-size: 11px;
      }}
      .node-section {{
        margin-top: 14px;
        padding-top: 12px;
        border-top: 1px solid {border};
      }}
      .node-section strong {{
        display: block;
        margin-bottom: 8px;
        font-size: 12px;
        letter-spacing: .06em;
        text-transform: uppercase;
        color: {muted};
      }}
      .node-list {{
        margin: 0;
        padding-left: 18px;
        color: {label_text};
        font-size: 12px;
        line-height: 1.6;
      }}
      .node-muted {{
        color: {muted};
        font-size: 12px;
      }}
    </style>
    <div id="mira-graph-shell">
      <div id="mira-graph"></div>
      <aside id="mira-node-panel" class="empty">
        <div class="node-kicker">Memory graph inspector</div>
        <div class="node-title">Click a node</div>
        <div class="node-headline">Open its source-backed memory details, connected edges, and evidence IDs.</div>
      </aside>
    </div>
    <script src="https://unpkg.com/3d-force-graph@1.73.4/dist/3d-force-graph.min.js"></script>
    <script>
      (function() {{
        const data = {data_json};
        const el = document.getElementById('mira-graph');
        const panel = document.getElementById('mira-node-panel');
        const overviewCamera = {{ z: 220 }};
        const emptyPanelHtml = `
          <div class="node-kicker">Memory graph inspector</div>
          <div class="node-title">Click a node</div>
          <div class="node-headline">Open its source-backed memory details, connected edges, and evidence IDs.</div>
        `;
        if (!window.ForceGraph3D) {{
          el.innerHTML = '<p style="color:{label_text};font-family:sans-serif;padding:1rem">3D graph needs internet access to load the renderer.</p>';
          return;
        }}
        const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({{
          '&': '&amp;',
          '<': '&lt;',
          '>': '&gt;',
          '"': '&quot;',
          "'": '&#39;'
        }}[char]));
        const nodeName = value => typeof value === 'object' ? value.name : value;
        const connectedLinks = node => data.links.filter(link =>
          nodeName(link.source) === node.id || nodeName(link.target) === node.id
        );
        const renderNode = node => {{
          const links = connectedLinks(node);
          const evidence = (node.evidence || []).map(item => `<li>${{escapeHtml(item)}}</li>`).join('');
          const edgeRows = links.map(link => {{
            const source = nodeName(link.source);
            const target = nodeName(link.target);
            const other = source === node.id ? target : source;
            const direction = source === node.id ? 'outgoing' : 'incoming';
            return `<li><b>${{escapeHtml(link.type || 'RELATED')}}</b> · ${{escapeHtml(direction)}} · ${{escapeHtml(other)}}</li>`;
          }}).join('');
          panel.classList.remove('empty');
          panel.innerHTML = `
            <div class="node-kicker">${{escapeHtml(node.type)}} · ${{escapeHtml(node.status)}}</div>
            <div class="node-title">${{escapeHtml(node.name)}}</div>
            <div class="node-headline">${{escapeHtml(node.headline)}}</div>
            <p class="node-summary">${{escapeHtml(node.summary)}}</p>
            <div class="node-pill-row">
              <span class="node-pill">id: ${{escapeHtml(node.id)}}</span>
              <span class="node-pill">${{links.length}} connected edge${{links.length === 1 ? '' : 's'}}</span>
            </div>
            <div class="node-section">
              <strong>Evidence IDs</strong>
              ${{evidence ? `<ul class="node-list">${{evidence}}</ul>` : '<div class="node-muted">No evidence attached.</div>'}}
            </div>
            <div class="node-section">
              <strong>Connected graph paths</strong>
              ${{edgeRows ? `<ul class="node-list">${{edgeRows}}</ul>` : '<div class="node-muted">No connected paths.</div>'}}
            </div>
          `;
        }};
        const closeNode = () => {{
          panel.classList.add('empty');
          panel.innerHTML = emptyPanelHtml;
          G.cameraPosition(overviewCamera, {{ x: 0, y: 0, z: 0 }}, 900);
        }};
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
          .onNodeClick(node => {{
            renderNode(node);
            const distance = 70;
            const distRatio = 1 + distance / Math.hypot(node.x || 1, node.y || 1, node.z || 1);
            G.cameraPosition(
              {{ x: (node.x || 0) * distRatio, y: (node.y || 0) * distRatio, z: (node.z || 0) * distRatio }},
              node,
              900
            );
          }})
          .onBackgroundClick(closeNode)
          .width(el.clientWidth)
          .height(460);
        G.cameraPosition(overviewCamera);
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


def _subhead(st: Any, title: str, subtitle: str) -> None:
    _unsafe(
        st,
        f"""
        <div class="section-title" style="margin-top:1.8rem">
          <h2>{escape(title)}</h2>
          <p class="muted">{escape(subtitle)}</p>
        </div>
        """,
    )


def _render_results(st: Any) -> None:
    _section_title(st, "Memory Verification", "Live result and the mechanisms behind it")
    tiles = "".join(
        f'<div class="tile"><small>{escape(stat["label"])}</small>'
        f"<strong>{escape(stat['value'])}</strong></div>"
        for stat in RESULT_STATS
    )
    _unsafe(st, f'<div class="tile-grid">{tiles}</div>')
    _unsafe(
        st,
        f'<p class="muted" style="margin-top:1rem;max-width:64ch">{escape(RESULT_ABSTRACT)}</p>',
    )

    _subhead(st, "Evidence", "Pulled from the run's databases — the scorer's claims, confirmed.")
    for ev in RESULT_EVIDENCE:
        states = ev["states"] if isinstance(ev["states"], list) else []
        chips = "".join(f'<span class="chip">{escape(str(state))}</span>' for state in states)
        _unsafe(
            st,
            f"""
            <div class="row-card">
              <div class="row-top"><strong>{escape(str(ev["title"]))}</strong>
              <span class="badge">{escape(str(ev["case"]))}</span></div>
              <p style="font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.84rem;color:var(--text);overflow-x:auto">{escape(str(ev["edge"]))}</p>
              <div class="chip-row">{chips}</div>
            </div>
            """,
        )

    _subhead(st, "How it was fixed", "Make pairing survive the model's inconsistency.")
    for fix in RESULT_FIXES:
        _unsafe(
            st,
            f"""
            <div class="row-card">
              <strong>{escape(fix["title"])}</strong>
              <p>{escape(fix["detail"])}</p>
            </div>
            """,
        )

    _subhead(st, "Full suite", "Ten cases · live DeepSeek · all passed.")
    cases = "".join(
        f'<div class="tile"><small>passed · {escape(case["mode"])}</small>'
        f"<strong>{escape(case['case'])}</strong></div>"
        for case in RESULT_CASES
    )
    _unsafe(st, f'<div class="tile-grid">{cases}</div>')

    _subhead(st, "Kept honest", "What isn't pristine yet.")
    for caveat in RESULT_CAVEATS:
        _unsafe(st, f'<div class="row-card"><p style="margin:0">{escape(caveat)}</p></div>')


_RENDERERS = {
    "Chat": _render_chat,
    "Graph": _render_memory_graph,
    "Working Set": _render_session_working_set,
    "Retrieval": _render_retrieval_trace,
    "Reflections": _render_reflections,
    "Communities": _render_communities,
    "Timeline": _render_timeline,
    "Results": _render_results,
}
