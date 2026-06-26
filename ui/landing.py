# ruff: noqa: E501
"""Marketing landing page for MIRA.

Ownership: Sarah.
Related issue: ISSUE-130.
Architecture area: UI.

A standalone, Claude-styled landing screen (hero, live 3D graph visual, feature
grid, how-it-works, footer) shown before the command center. The primary call to
action launches the app by setting ``mira_entered`` in session state.
"""

from __future__ import annotations

from html import escape
from textwrap import dedent
from typing import Any

from ui.command_center import _graph_3d_html

_FEATURES: tuple[tuple[str, str, str], ...] = (
    (
        "memory",
        "Durable slow-path memory",
        "Confirmed facts are promoted into cross-session memory tiers — context compounds instead of vanishing when the chat ends.",
    ),
    (
        "radar",
        "Foresight detection",
        "MIRA flags future-relevant commitments as they happen, so deadlines and intents resurface exactly when they matter.",
    ),
    (
        "auto_awesome",
        "Gated reflection",
        "Once enough evidence accumulates, MIRA synthesizes higher-order insights — never noisily on every single turn.",
    ),
    (
        "hub",
        "Typed temporal graph",
        "Entities and relations form a time-aware graph, with communities and summaries detected via Leiden over the topology.",
    ),
    (
        "bolt",
        "Two-speed retrieval",
        "A fast quick path for live working context and a deep path for evidence-backed, cross-session recall.",
    ),
    (
        "verified",
        "Evidence & contradictions",
        "Every memory is source-backed; contradictions are detected and superseded rather than silently duplicated.",
    ),
)

_STEPS: tuple[tuple[str, str, str], ...] = (
    (
        "01",
        "Observe",
        "Every message becomes an observation in the session working set, captured with its context.",
    ),
    (
        "02",
        "Consolidate",
        "The slow path confirms, promotes, extracts atomic facts, links the graph, and reflects.",
    ),
    (
        "03",
        "Recall",
        "Quick and deep retrieval surface the right memory at the right time — always with evidence.",
    ),
)


def _enter_app(st: Any) -> None:
    """on_click callback: launch the command center on the next run."""
    st.session_state["mira_entered"] = True


def _unsafe(st: Any, markup: str) -> None:
    st.markdown(dedent(markup).strip(), unsafe_allow_html=True)


def render_landing(st: Any) -> None:
    """Render the MIRA marketing landing page."""
    theme = str(st.session_state.get("mira_theme", "dark"))
    st.markdown(_landing_css(theme), unsafe_allow_html=True)

    # --- Top nav ---
    nav_l, nav_r = st.columns([0.7, 0.3], vertical_alignment="center")
    with nav_l:
        _unsafe(st, '<div class="lp-brand"><span class="spark">✻</span>&nbsp;MIRA</div>')
    with nav_r:
        st.button("Launch app →", key="nav_launch", on_click=_enter_app, args=(st,))

    # --- Hero ---
    _unsafe(
        st,
        """
        <div class="lp-hero">
          <div class="lp-eyebrow">Memory-Integrated Reasoning Architecture</div>
          <h1 class="lp-title">The memory layer for AI<br/>that actually remembers.</h1>
          <p class="lp-sub">MIRA turns every conversation into durable, structured, retrievable
          knowledge — so your assistant compounds context across sessions instead of forgetting it.</p>
        </div>
        """,
    )
    spacer_l, cta_l, cta_r, spacer_r = st.columns([0.32, 0.18, 0.18, 0.32])
    with cta_l:
        st.button("Launch MIRA  →", key="hero_launch", on_click=_enter_app, args=(st,))
    with cta_r:
        st.button("How it works", key="hero_docs")

    # --- Live graph visual ---
    _unsafe(st, '<div class="lp-visual-cap">A living, typed memory graph</div>')
    st.components.v1.html(_graph_3d_html(theme), height=420)

    # --- Features ---
    _unsafe(st, '<h2 class="lp-h2">One memory, many capabilities</h2>')
    cols = st.columns(3, gap="medium")
    for index, (icon, title, desc) in enumerate(_FEATURES):
        with cols[index % 3]:
            _unsafe(
                st,
                f"""
                <div class="feature">
                  <span class="msi">{escape(icon)}</span>
                  <h3>{escape(title)}</h3>
                  <p>{escape(desc)}</p>
                </div>
                """,
            )

    # --- How it works ---
    _unsafe(st, '<h2 class="lp-h2">How it works</h2>')
    step_cols = st.columns(3, gap="medium")
    for col, (num, title, desc) in zip(step_cols, _STEPS, strict=False):
        with col:
            _unsafe(
                st,
                f"""
                <div class="step">
                  <span class="step-num">{escape(num)}</span>
                  <h3>{escape(title)}</h3>
                  <p>{escape(desc)}</p>
                </div>
                """,
            )

    # --- Closing CTA + footer ---
    _unsafe(
        st,
        """
        <div class="lp-closing">
          <h2>Give your assistant a memory worth keeping.</h2>
        </div>
        """,
    )
    s_l, c_mid, s_r = st.columns([0.4, 0.2, 0.4])
    with c_mid:
        st.button("Launch MIRA  →", key="closing_launch", on_click=_enter_app, args=(st,))
    _unsafe(
        st,
        '<div class="lp-footer">MIRA · Memory-Integrated Reasoning Architecture · Built for durable reasoning</div>',
    )


def _landing_css(theme: str) -> str:
    safe = "light" if theme == "light" else "dark"
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@24,400,0,0');

:root, [data-testid="stAppViewContainer"] {{
  --bg: {"#f4f3ee" if safe == "light" else "#1c1b1a"};
  --surface: {"#ffffff" if safe == "light" else "#262624"};
  --surface-soft: {"#faf9f5" if safe == "light" else "#30302e"};
  --text: {"#2d2c28" if safe == "light" else "#f3f2ec"};
  --muted: {"#6b6a62" if safe == "light" else "#a3a299"};
  --faint: {"#908f86" if safe == "light" else "#7d7c73"};
  --border: {"#e6e4da" if safe == "light" else "#3a3937"};
  --border-strong: {"#d6d3c6" if safe == "light" else "#54534f"};
  --accent: {"#cc785c" if safe == "light" else "#d97757"};
  --accent-soft: {"rgba(204,120,92,.12)" if safe == "light" else "rgba(217,119,87,.16)"};
  --shadow: {"0 1px 3px rgba(50,40,30,.06), 0 10px 30px rgba(50,40,30,.06)" if safe == "light" else "0 1px 3px rgba(0,0,0,.3)"};
}}

html, body, [data-testid="stAppViewContainer"] {{
  color: var(--text) !important;
  font-family: ui-sans-serif, -apple-system, "Segoe UI", Inter, system-ui, sans-serif;
  background: var(--bg) !important;
}}
[data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stHeader"], footer {{ display: none !important; }}

.block-container {{ max-width: 1080px !important; padding: 1.4rem 1.6rem 4rem !important; }}

.msi {{ font-family: 'Material Symbols Rounded'; font-size: 1.6rem; line-height: 1; color: var(--accent); }}

.lp-brand {{ font-size: 1.3rem; font-weight: 700; letter-spacing: -.02em; }}
.spark {{ color: var(--accent); }}

/* ---- Hero ---- */
.lp-hero {{ text-align: center; margin: 3.4rem 0 1.6rem; }}
.lp-eyebrow {{
  display: inline-block;
  color: var(--accent);
  background: var(--accent-soft);
  padding: 6px 14px;
  border-radius: 999px;
  font-size: .8rem;
  font-weight: 600;
  letter-spacing: .02em;
  margin-bottom: 1.4rem;
}}
.lp-title {{
  font-family: Georgia, "Times New Roman", serif;
  font-size: 3.4rem;
  line-height: 1.08;
  letter-spacing: -.03em;
  margin: 0 0 1.2rem;
  color: var(--text);
}}
.lp-sub {{
  max-width: 640px;
  margin: 0 auto;
  color: var(--muted);
  font-size: 1.12rem;
  line-height: 1.6;
}}

/* CTA buttons */
.st-key-hero_launch .stButton > button, .st-key-closing_launch .stButton > button {{
  width: 100%;
  border-radius: 12px;
  padding: 12px 18px;
  font-weight: 700;
  font-size: .96rem;
  color: #fff;
  border: none;
  background: var(--accent);
  box-shadow: 0 12px 30px rgba(217,119,87,.28);
}}
.st-key-hero_launch .stButton > button:hover, .st-key-closing_launch .stButton > button:hover {{ color: #fff; background: var(--accent); filter: brightness(1.05); }}

.st-key-hero_docs .stButton > button {{
  width: 100%;
  border-radius: 12px;
  padding: 12px 18px;
  font-weight: 600;
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--border-strong);
}}
.st-key-nav_launch .stButton > button {{
  border-radius: 10px;
  padding: 8px 16px;
  font-weight: 600;
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--border-strong);
}}
.st-key-nav_launch {{ display: flex; justify-content: flex-end; }}

.lp-visual-cap {{ text-align: center; color: var(--faint); font-size: .82rem; letter-spacing: .04em; text-transform: uppercase; margin: 3rem 0 .4rem; }}

/* ---- Sections ---- */
.lp-h2 {{
  font-family: Georgia, "Times New Roman", serif;
  font-size: 1.9rem;
  letter-spacing: -.02em;
  text-align: center;
  margin: 3.4rem 0 1.8rem;
  color: var(--text);
}}

.feature {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 22px;
  height: 100%;
  box-shadow: var(--shadow);
}}
.feature h3 {{ margin: 14px 0 8px; font-size: 1.06rem; color: var(--text); letter-spacing: -.01em; }}
.feature p {{ margin: 0; color: var(--muted); font-size: .92rem; line-height: 1.6; }}

.step {{ padding: 8px 4px; }}
.step-num {{
  display: inline-grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border-radius: 50%;
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 700;
  font-size: .9rem;
}}
.step h3 {{ margin: 14px 0 8px; font-size: 1.1rem; color: var(--text); }}
.step p {{ margin: 0; color: var(--muted); font-size: .92rem; line-height: 1.6; }}

.lp-closing {{ text-align: center; margin: 4rem 0 1.4rem; }}
.lp-closing h2 {{ font-family: Georgia, "Times New Roman", serif; font-size: 2rem; letter-spacing: -.02em; color: var(--text); }}

.lp-footer {{ text-align: center; color: var(--faint); font-size: .82rem; margin-top: 3rem; padding-top: 1.6rem; border-top: 1px solid var(--border); }}
</style>
"""
