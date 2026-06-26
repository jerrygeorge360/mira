"""Premium Streamlit Memory Command Center renderer for MIRA.

Ownership: Sarah.
Related issue: ISSUE-130.
Architecture area: UI.
"""

from __future__ import annotations

from html import escape
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


def render_command_center(st: Any) -> None:
    """Render the production-quality Memory Command Center UI."""
    _init_state(st)
    theme = _theme_control(st)
    st.markdown(command_center_css(theme), unsafe_allow_html=True)
    st.markdown(_shell_html(theme), unsafe_allow_html=True)


def _init_state(st: Any) -> None:
    state = st.session_state
    state.setdefault("mira_theme", "dark")
    state.setdefault("mira_nav", "Command Center")
    state.setdefault("mira_chat_draft", "")


def _theme_control(st: Any) -> str:
    state = st.session_state
    current_theme = str(state.get("mira_theme", "dark"))
    dark_mode = current_theme != "light"
    toggle = st.toggle("Dark mode", value=dark_mode, key="mira_theme_toggle")
    state["mira_theme"] = "dark" if toggle else "light"
    return str(state["mira_theme"])


def _shell_html(theme: str) -> str:
    return f"""
<div class="mira-shell" data-theme="{escape(theme)}">
  <div class="mira-grid">
    {_sidebar_html()}
    {_topbar_html(theme)}
    {_chat_panel_html()}
    <div class="right-stack">
      {_memory_graph_html()}
      {_session_working_set_html()}
      {_retrieval_trace_html()}
      {_reflections_html()}
      {_communities_html()}
    </div>
    {_timeline_html()}
  </div>
</div>
"""


def _sidebar_html() -> str:
    nav = "\n".join(
        f"""
        <div class="nav-item {'active' if item['label'] == 'Command Center' else ''}">
          <span class="nav-icon">{escape(item['icon'])}</span>
          <span>{escape(item['label'])}</span>
        </div>
        """
        for item in NAV_ITEMS
    )
    return f"""
<aside class="sidebar glass">
  <div class="brand">
    <div class="logo-mark">M</div>
    <div>
      <h1>MIRA</h1>
      <p>Memory Command Center</p>
    </div>
  </div>
  <nav class="nav-stack">{nav}</nav>
  <div class="sidebar-bottom">
    <div class="status-card">
      <div class="status-online"><span class="pulse"></span>MIRA ONLINE</div>
      <div class="metric-grid" style="margin-top:12px;">
        <div class="metric-tile"><small>Memories</small><strong>12.8k</strong></div>
        <div class="metric-tile"><small>Context</small><strong>72%</strong></div>
      </div>
    </div>
    <div class="primary-btn">Optimize Memory</div>
  </div>
</aside>
"""


def _topbar_html(theme: str) -> str:
    theme_label = "Dark" if theme == "dark" else "Light"
    return f"""
<header class="topbar glass">
  <div class="toolbar-left">
    <div class="model-chip">● MIRA 3.1 PRO</div>
    <div class="chip">Workspace: <strong>&nbsp;Personal OS</strong></div>
    <div class="search-box">⌕ Search memories, people, projects...</div>
  </div>
  <div class="toolbar-right">
    <div class="chip">Theme: <strong>&nbsp;{escape(theme_label)}</strong></div>
    <div class="icon-btn">🔔</div>
    <div class="profile-chip"><span class="avatar">JG</span><span>Jerry</span></div>
  </div>
</header>
"""


def _chat_panel_html() -> str:
    messages = "\n".join(_chat_message_html(message) for message in CHAT_MESSAGES)
    return f"""
<main class="chat-panel command-card glass">
  <div class="chat-title">
    <div>
      <div style="display:flex; gap:10px; align-items:center;">
        <h2>MIRA</h2><span class="badge">PRO</span>
      </div>
      <p class="muted">Your Memory. Your Advantage.</p>
    </div>
    <span class="badge">94% context certainty</span>
  </div>
  <section class="chat-stream">
    {messages}
    {_brief_card_html()}
    {_action_chips_html()}
  </section>
  <div class="composer">
    <div class="icon-btn">＋</div>
    <div class="composer-input">Ask MIRA anything about your memory...</div>
    <div class="icon-btn">🎙</div>
    <div class="send-btn">➜</div>
  </div>
</main>
"""


def _chat_message_html(message: dict[str, str]) -> str:
    role = escape(message["role"])
    content = escape(message["content"])
    label = "You" if role == "user" else "MIRA"
    return f"""
<div class="bubble {role}">
  <small class="muted">{label}</small>
  <div>{content}</div>
</div>
"""


def _brief_card_html() -> str:
    details = "\n".join(
        f"""
        <div class="brief-item">
          <small>{escape(item['label'])}</small>
          <strong>{escape(item['value'])}</strong>
        </div>
        """
        for item in BRIEF_DETAILS
    )
    return f"""
<article class="brief-card">
  <div class="row-top" style="margin-bottom:14px;">
    <div>
      <h3 style="margin:0;">NovaDynamics Meeting Brief</h3>
      <p class="muted">Synthesized from graph paths, recent turns, and durable memory.</p>
    </div>
    <span class="badge">27 sources</span>
  </div>
  <div class="brief-grid">{details}</div>
</article>
"""


def _action_chips_html() -> str:
    chips = "".join(f'<span class="chip">{escape(chip)}</span>' for chip in ACTION_CHIPS)
    return f'<div class="chip-row">{chips}</div>'


def _memory_graph_html() -> str:
    metrics = "".join(
        f'<div class="metric-tile"><small>{escape(item["label"])}</small>'
        f'<strong>{escape(item["value"])}</strong></div>'
        for item in GRAPH_METRICS
    )
    return f"""
<section class="command-card glass memory-graph">
  {_panel_title("Memory Graph", "Live topology mock")}
  <div class="graph-stage">
    <div class="edge e1"></div><div class="edge e2"></div>
    <div class="edge e3"></div><div class="edge e4"></div>
    <div class="node main">MIRA</div>
    <div class="node n1">You</div>
    <div class="node n2">Docs</div>
    <div class="node n3">Tasks</div>
    <div class="node n4">Graph</div>
  </div>
  <div class="metric-grid" style="margin-top:12px;">{metrics}</div>
</section>
"""


def _session_working_set_html() -> str:
    def _priority(item: dict[str, str]) -> str:
        priority = escape(item["priority"])
        priority_class = escape(item["priority"].lower())
        return f'<small class="priority-{priority_class}">{priority}</small>'

    rows = "".join(
        f"""
        <div class="memory-row">
          <div class="row-top">
            <strong>{escape(item['title'])}</strong>
            <span class="badge">{escape(item['type'])}</span>
          </div>
          <div class="row-top" style="margin-top:8px;">
            <small class="muted">{escape(item['scope'])}</small>
            {_priority(item)}
          </div>
        </div>
        """
        for item in SESSION_ITEMS
    )
    return f"""
<section class="command-card glass">
  {_panel_title("Session Working Set", "5 active items")}
  <div class="row-top"><small class="muted">Context limit</small><small>72%</small></div>
  <div class="progress-track"><div class="progress-bar"></div></div>
  <div class="list-stack">{rows}</div>
</section>
"""


def _retrieval_trace_html() -> str:
    rows = "".join(
        f"""
        <div class="evidence-row">
          <div class="row-top">
            <span class="badge">{escape(item['rank'])}</span>
            <small class="muted">score {escape(item['score'])}</small>
          </div>
          <strong>{escape(item['title'])}</strong>
          <div class="muted">{escape(item['source'])}</div>
        </div>
        """
        for item in EVIDENCE_ITEMS
    )
    return f"""
<section class="command-card glass">
  {_panel_title("Retrieval Trace", "Evidence & Reasoning")}
  <div class="brief-item">
    <small>User query</small>
    <strong>Prepare me for NovaDynamics.</strong>
  </div>
  <div class="metric-grid" style="margin:10px 0;">
    <div class="metric-tile"><small>Retrieved</small><strong>27</strong></div>
    <div class="metric-tile"><small>Confidence</small><strong>94%</strong></div>
  </div>
  <div class="list-stack">{rows}</div>
  <div class="chip-row"><span class="chip">View full trace →</span></div>
</section>
"""


def _reflections_html() -> str:
    cards = "".join(
        f"""
        <div class="reflection-card">
          <small class="muted">{escape(str(item['time']))}</small>
          <p style="margin:.35rem 0 .55rem;">{escape(str(item['insight']))}</p>
          <div class="chip-row" style="margin-top:0;">{_tags_html(item['tags'])}</div>
        </div>
        """
        for item in REFLECTIONS
    )
    return f"""
<section class="command-card glass">
  {_panel_title("Reflections", "Synthesized insights")}
  <div class="list-stack">{cards}</div>
</section>
"""


def _communities_html() -> str:
    def _summary(item: dict[str, str]) -> str:
        people = escape(item["people"])
        insights = escape(item["insights"])
        return f'<small class="muted">{people} people · {insights} insights</small>'

    rows = "".join(
        f"""
        <div class="community-row">
          <div class="row-top">
            <strong>{escape(item['title'])}</strong>
            <span class="badge">{escape(item['delta'])}</span>
          </div>
          {_summary(item)}
        </div>
        """
        for item in COMMUNITIES
    )
    return f"""
<section class="command-card glass">
  {_panel_title("Community Summaries", "Trending clusters")}
  <div class="list-stack">{rows}</div>
</section>
"""


def _timeline_html() -> str:
    tabs = "".join(
        f'<span class="chip {"active" if tab == "All" else ""}">{tab}</span>'
        for tab in ("All", "Memories", "Events", "Tasks", "Milestones")
    )
    cards = "".join(
        f"""
        <div class="timeline-card">
          <div class="timeline-body">
            <small class="muted">{escape(item['when'])} · {escape(item['kind'])}</small>
            <h4 style="margin:.45rem 0 0;">{escape(item['title'])}</h4>
          </div>
        </div>
        """
        for item in TIMELINE
    )
    return f"""
<section class="timeline glass">
  {_panel_title("Timeline", "Past · Today · Future")}
  <div class="timeline-tabs">{tabs}</div>
  <div class="timeline-strip">{cards}</div>
</section>
"""


def _panel_title(title: str, subtitle: str) -> str:
    return f"""
<div class="panel-title">
  <div>
    <h3>{escape(title)}</h3>
    <p class="muted">{escape(subtitle)}</p>
  </div>
  <span class="badge">LIVE</span>
</div>
"""


def _tags_html(tags: object) -> str:
    if not isinstance(tags, list):
        return ""
    return "".join(f'<span class="chip">{escape(str(tag))}</span>' for tag in tags)
