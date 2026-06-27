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

_OFFICIAL_BENCHMARKS: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "LongMemEval",
        "Long-term cross-session recall",
        "Durable memory tiers + Quick/Deep retrieval",
        "Recall / evidence F1",
        "Planned / runner ready",
    ),
    (
        "LoCoMo-style",
        "Temporal conversational memory",
        "Observation log + slow-path consolidation",
        "Temporal QA accuracy",
        "Prototype adapter",
    ),
)

_ABLATION_STUDIES: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "Remove Session Working Set",
        "Immediate corrections stop affecting the next response reliably",
        "Session Working Set + confirmation gate",
        "Next-turn compliance",
        "Result pending",
    ),
    (
        "Remove typed graph traversal",
        "Change and relationship questions lose evidence paths",
        "Typed temporal graph edges",
        "Change classification F1",
        "Result pending",
    ),
    (
        "Remove reflections/community summaries",
        "Long-horizon synthesis becomes shallow or repetitive",
        "Reflections + community summaries",
        "Judge synthesis score",
        "Result pending",
    ),
    (
        "Remove foresight records",
        "Deadlines and future commitments stop resurfacing at the right time",
        "Foresight records + ambient context",
        "Activation precision",
        "Result pending",
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
    nav_l, nav_mid, nav_r = st.columns([0.26, 0.5, 0.24], vertical_alignment="center")
    with nav_l:
        _unsafe(st, '<div class="lp-brand"><span class="spark">✻</span>&nbsp;MIRA</div>')
    with nav_mid:
        _unsafe(
            st,
            """
            <div class="lp-nav-links">
              <a href="#capabilities">Capabilities</a>
              <a href="#how-it-works">How it works</a>
              <a href="#architecture">Architecture</a>
              <a href="#benchmarks">Benchmarks</a>
              <a href="#ablation-studies">Ablations</a>
            </div>
            """,
        )
    with nav_r:
        st.button("Launch app →", key="nav_launch", on_click=_enter_app, args=(st,))

    # --- Hero ---
    _unsafe(
        st,
        """
        <div class="lp-hero">
          <div class="lp-eyebrow">Memory-Integrated Reasoning Architecture</div>
          <h1 class="lp-title">Give your AI a memory<br/>it can actually trust.</h1>
          <p class="lp-sub">MIRA turns conversations into source-backed observations, atomic facts,
          graph relationships, foresight, reflections, and community summaries — so context compounds
          without becoming a pile of unverified notes.</p>
        </div>
        """,
    )
    spacer_l, cta_l, cta_r, spacer_r = st.columns([0.32, 0.18, 0.18, 0.32])
    with cta_l:
        st.button("Launch MIRA  →", key="hero_launch", on_click=_enter_app, args=(st,))
    with cta_r:
        _unsafe(st, '<a href="#how-it-works" class="lp-ghost-btn">How it works</a>')

    # --- Product visual ---
    _unsafe(
        st, '<div class="lp-visual-cap">A calm command surface over a living memory graph</div>'
    )
    st.components.v1.html(_landing_memory_visual(theme), height=390)

    # --- Features ---
    _unsafe(
        st,
        '<div id="capabilities" class="lp-anchor"></div><h2 class="lp-h2">One memory, many capabilities</h2>',
    )
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
    _unsafe(
        st, '<div id="how-it-works" class="lp-anchor"></div><h2 class="lp-h2">How it works</h2>'
    )
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

    _unsafe(
        st,
        """
        <div class="architecture-strip" id="architecture">
          <div><span>01</span><strong>Session Working Set</strong><p>Immediate corrections and constraints shape the next response.</p></div>
          <div><span>02</span><strong>Slow Path</strong><p>Facts, entities, graph edges, foresight, reflections, and tiers consolidate safely.</p></div>
          <div><span>03</span><strong>Retrieval Modes</strong><p>Quick, Deep, Relational, and Auto modes select the right memory surface.</p></div>
        </div>
        """,
    )

    # --- Evaluation ---
    _unsafe(
        st,
        """
        <section class="lp-section-intro" id="benchmarks">
          <h2 class="lp-h2">Built to be evaluated, not just demoed</h2>
          <p class="lp-section-sub">
            MIRA separates official benchmark results from ablation studies.
            Benchmarks test the whole system against standard memory tasks;
            ablations remove one MIRA component at a time to measure what breaks.
          </p>
        </section>
        """,
    )
    _unsafe(
        st,
        '<div id="official-benchmarks" class="lp-anchor"></div><h3 class="lp-mini-h">Official benchmark tracks</h3>',
    )
    _render_evaluation_cards(st, _OFFICIAL_BENCHMARKS, metric_label="Metric to report")
    _unsafe(
        st,
        '<div id="ablation-studies" class="lp-anchor"></div><h3 class="lp-mini-h">Ablation studies</h3>',
    )
    _render_evaluation_cards(st, _ABLATION_STUDIES, metric_label="Ablation metric")

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


def _landing_memory_visual(theme: str) -> str:
    """Return a self-contained Claude-style memory visual for the landing page."""
    safe = "light" if theme == "light" else "dark"
    bg = "#f8f6ef" if safe == "light" else "#22211f"
    surface = "#ffffff" if safe == "light" else "#2b2a28"
    text = "#2d2c28" if safe == "light" else "#f3f2ec"
    muted = "#777268" if safe == "light" else "#a6a197"
    border = "#e5e0d3" if safe == "light" else "#413f3b"
    accent = "#cc785c" if safe == "light" else "#d97757"
    return f"""
<!doctype html>
<html>
<head>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: transparent;
    font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    color: {text};
  }}
  .visual {{
    height: 372px;
    border: 1px solid {border};
    border-radius: 28px;
    background:
      radial-gradient(circle at 20% 0%, rgba(204,120,92,.16), transparent 240px),
      {bg};
    overflow: hidden;
    display: grid;
    grid-template-columns: 1.1fr .9fr;
    gap: 18px;
    padding: 24px;
    box-shadow: 0 22px 60px rgba(0,0,0,.10);
  }}
  .graph {{
    position: relative;
    border-radius: 22px;
    border: 1px solid {border};
    background: {surface};
    min-height: 100%;
    overflow: hidden;
  }}
  .line {{
    position: absolute;
    height: 1px;
    background: linear-gradient(90deg, transparent, {accent}, transparent);
    opacity: .5;
    transform-origin: left center;
  }}
  .l1 {{ width: 210px; left: 120px; top: 112px; transform: rotate(18deg); }}
  .l2 {{ width: 180px; left: 140px; top: 190px; transform: rotate(-24deg); }}
  .l3 {{ width: 160px; left: 210px; top: 150px; transform: rotate(48deg); }}
  .l4 {{ width: 140px; left: 72px; top: 210px; transform: rotate(36deg); }}
  .node {{
    position: absolute;
    display: grid;
    place-items: center;
    border-radius: 999px;
    border: 1px solid {border};
    background: {bg};
    color: {text};
    font-weight: 700;
    box-shadow: 0 10px 30px rgba(0,0,0,.08);
  }}
  .n-main {{ width: 92px; height: 92px; left: calc(50% - 46px); top: 118px; color: {accent}; }}
  .n-a {{ width: 70px; height: 70px; left: 46px; top: 62px; }}
  .n-b {{ width: 76px; height: 76px; right: 58px; top: 58px; }}
  .n-c {{ width: 68px; height: 68px; left: 82px; bottom: 58px; }}
  .n-d {{ width: 84px; height: 84px; right: 76px; bottom: 52px; }}
  .side {{
    display: grid;
    gap: 12px;
    align-content: center;
  }}
  .card {{
    background: {surface};
    border: 1px solid {border};
    border-radius: 18px;
    padding: 16px;
  }}
  .card small {{
    display: block;
    color: {muted};
    margin-bottom: 6px;
  }}
  .card strong {{
    font-size: 16px;
  }}
  .status {{
    color: {accent};
    font-weight: 750;
  }}
</style>
</head>
<body>
  <div class="visual">
    <div class="graph" aria-label="MIRA memory graph illustration">
      <div class="line l1"></div><div class="line l2"></div><div class="line l3"></div><div class="line l4"></div>
      <div class="node n-main">MIRA</div>
      <div class="node n-a">Facts</div>
      <div class="node n-b">Graph</div>
      <div class="node n-c">Future</div>
      <div class="node n-d">Reflect</div>
    </div>
    <div class="side">
      <div class="card"><small>Active memory surface</small><strong>Session correction overrides durable memory temporarily</strong></div>
      <div class="card"><small>Slow path</small><strong>12 observations consolidated · <span class="status">healthy</span></strong></div>
      <div class="card"><small>Retrieval</small><strong>Quick + Deep + Relational evidence ready</strong></div>
    </div>
  </div>
</body>
</html>
"""


def _render_evaluation_cards(
    st: Any,
    rows: tuple[tuple[str, str, str, str, str], ...],
    *,
    metric_label: str,
) -> None:
    """Render evaluation rows as polished responsive cards."""
    columns = st.columns(2, gap="medium")
    for index, (track, tests, mechanism, metric, status) in enumerate(rows):
        with columns[index % 2]:
            _unsafe(
                st,
                f"""
                <article class="bench-card">
                  <div class="bench-card-top">
                    <span class="bench-track">{escape(track)}</span>
                    <span class="bench-status">{escape(status)}</span>
                  </div>
                  <p class="bench-tests">{escape(tests)}</p>
                  <div class="bench-mechanism">
                    <span>MIRA mechanism</span>
                    <strong>{escape(mechanism)}</strong>
                  </div>
                  <div class="bench-metric">
                    <span>{escape(metric_label)}</span>
                    <strong>{escape(metric)}</strong>
                  </div>
                </article>
                """,
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

html {{ scroll-behavior: smooth; }}
html, body, [data-testid="stAppViewContainer"] {{
  color: var(--text) !important;
  font-family: ui-sans-serif, -apple-system, "Segoe UI", Inter, system-ui, sans-serif;
  background: var(--bg) !important;
}}
[data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stHeader"], footer {{ display: none !important; }}

.block-container {{ max-width: 1080px !important; padding: 1.4rem 1.6rem 4rem !important; }}
.st-key-cc_rail {{ display: none !important; }}

.msi {{ font-family: 'Material Symbols Rounded'; font-size: 1.6rem; line-height: 1; color: var(--accent); }}

.lp-brand {{ font-size: 1.3rem; font-weight: 700; letter-spacing: -.02em; }}
.spark {{ color: var(--accent); }}
.lp-nav-links {{
  display: flex;
  justify-content: center;
  gap: 18px;
  color: var(--muted);
  font-size: .92rem;
}}
.lp-nav-links a {{
  color: var(--muted) !important;
  text-decoration: none !important;
}}
.lp-nav-links a:hover {{ color: var(--accent) !important; }}

/* ---- Hero ---- */
.lp-hero {{ text-align: center; margin: 3.4rem 0 1.6rem; }}
.lp-hero > * {{
  margin-left: auto !important;
  margin-right: auto !important;
}}
.lp-hero h1, .lp-hero p, .lp-hero div {{
  text-align: center !important;
}}
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
  margin: 0 auto 1.2rem;
  text-align: center !important;
  color: var(--text);
}}
.lp-sub {{
  max-width: 640px;
  margin: 0 auto;
  text-align: center !important;
  color: var(--muted);
  font-size: 1.12rem;
  line-height: 1.6;
}}

/* Anchor styled as a secondary button (scrolls to #how-it-works). */
.lp-ghost-btn {{
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  padding: 12px 18px;
  border-radius: 12px;
  border: 1px solid var(--border-strong);
  background: var(--surface);
  color: var(--text) !important;
  font-weight: 600;
  font-size: .96rem;
  text-decoration: none !important;
}}
.lp-ghost-btn:hover {{ border-color: var(--accent); color: var(--accent) !important; }}
/* Offset anchor targets so headings do not hide under the browser chrome. */
.lp-anchor,
#architecture,
#benchmarks,
#official-benchmarks,
#ablation-studies {{
  scroll-margin-top: 2.5rem;
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
  margin-bottom: 18px;
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

.architecture-strip {{
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1px;
  margin: 3.2rem 0 1rem;
  border: 1px solid var(--border);
  border-radius: 18px;
  overflow: hidden;
  background: var(--border);
  box-shadow: var(--shadow);
}}
.architecture-strip > div {{
  background: var(--surface);
  padding: 22px;
}}
.architecture-strip span {{
  color: var(--accent);
  font-size: .82rem;
  font-weight: 700;
}}
.architecture-strip strong {{
  display: block;
  margin: 10px 0 8px;
  color: var(--text);
}}
.architecture-strip p {{
  margin: 0;
  color: var(--muted);
  font-size: .92rem;
  line-height: 1.55;
}}

.lp-section-intro {{
  width: 100%;
  margin: 3.4rem auto 1.6rem;
  text-align: center !important;
}}
.lp-section-intro .lp-h2 {{
  margin-top: 0;
  margin-bottom: 1.2rem;
}}
.lp-section-sub {{
  display: block;
  max-width: 680px;
  margin: 0 auto 1.8rem !important;
  padding: 0 12px;
  text-align: center !important;
  color: var(--muted);
  font-size: .98rem;
  line-height: 1.65;
}}
.lp-mini-h {{
  margin: 2.2rem 0 1rem;
  color: var(--text);
  font-size: 1.05rem;
  font-weight: 850;
  letter-spacing: -.01em;
  text-align: center;
}}

.bench-card {{
  position: relative;
  min-height: 166px;
  margin-bottom: 1rem;
  padding: 18px;
  border: 1px solid var(--border);
  border-radius: 20px;
  background:
    radial-gradient(circle at top right, var(--accent-soft), transparent 38%),
    linear-gradient(180deg, var(--surface), var(--surface-soft));
  box-shadow: var(--shadow);
  overflow: hidden;
}}
.bench-card::before {{
  content: "";
  position: absolute;
  inset: 0 auto 0 0;
  width: 3px;
  background: linear-gradient(180deg, var(--accent), transparent);
  opacity: .75;
}}
.bench-card-top {{
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 12px;
}}
.bench-track {{
  color: var(--text);
  font-size: 1rem;
  font-weight: 800;
  letter-spacing: -.01em;
}}
.bench-status {{
  display: inline-flex;
  flex: 0 0 auto;
  white-space: nowrap;
  color: var(--accent);
  background: var(--accent-soft);
  border-radius: 999px;
  padding: 5px 10px;
  font-size: .78rem;
  font-weight: 700;
}}
.bench-tests {{
  margin: 0 0 14px;
  color: var(--muted);
  font-size: .94rem;
  line-height: 1.55;
}}
.bench-mechanism {{
  border-top: 1px solid var(--border);
  padding-top: 12px;
}}
.bench-metric {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 12px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: color-mix(in srgb, var(--accent-soft) 42%, transparent);
}}
.bench-mechanism span, .bench-metric span {{
  display: block;
  color: var(--faint);
  font-size: .72rem;
  font-weight: 800;
  letter-spacing: .08em;
  text-transform: uppercase;
}}
.bench-mechanism span {{ margin-bottom: 5px; }}
.bench-mechanism strong {{
  color: var(--text);
  font-size: .9rem;
  line-height: 1.45;
}}
.bench-metric strong {{
  color: var(--accent);
  font-size: .86rem;
  text-align: right;
}}

.lp-closing {{ text-align: center; margin: 4rem 0 1.4rem; }}
.lp-closing h2 {{ font-family: Georgia, "Times New Roman", serif; font-size: 2rem; letter-spacing: -.02em; color: var(--text); }}

.lp-footer {{ text-align: center; color: var(--faint); font-size: .82rem; margin-top: 3rem; padding-top: 1.6rem; border-top: 1px solid var(--border); }}

@media (max-width: 760px) {{
  .lp-nav-links {{ display: none; }}
  .lp-title {{ font-size: 2.35rem; }}
  .architecture-strip {{ grid-template-columns: 1fr; }}
  .bench-card {{ min-height: auto; }}
}}
</style>
"""
