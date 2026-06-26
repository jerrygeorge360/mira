# ruff: noqa: E501
"""Custom CSS for the MIRA Memory Command Center.

Ownership: Sarah.
Related issue: ISSUE-130.
Architecture area: UI.

The renderer (``ui/command_center.py``) is a single screen with top-level tabs.
This stylesheet themes the slim header, the tab bar (the primary navigation), the
native widgets (buttons, inputs, metrics, progress), and the hand-written HTML
fragments. Theme variables live on a global scope so they cascade onto native
Streamlit widgets, not just the hand-written HTML.
"""

from __future__ import annotations


def command_center_css(theme: str) -> str:
    """Return the custom CSS layer for the selected theme."""
    safe_theme = "light" if theme == "light" else "dark"
    return f"""
<style>
:root, [data-testid="stAppViewContainer"] {{
  --radius-xl: 24px;
  --radius-lg: 18px;
  --radius-md: 14px;
  --ease: cubic-bezier(.2,.8,.2,1);
  --bg: {"#eef3fb" if safe_theme == "light" else "#050812"};
  --bg-2: {"#f8fbff" if safe_theme == "light" else "#09111f"};
  --panel: {"rgba(255,255,255,.80)" if safe_theme == "light" else "rgba(13, 22, 38, .72)"};
  --panel-strong: {"rgba(255,255,255,.94)" if safe_theme == "light" else "rgba(18, 30, 52, .94)"};
  --panel-soft: {"rgba(239,246,255,.84)" if safe_theme == "light" else "rgba(10, 18, 32, .55)"};
  --text: {"#111827" if safe_theme == "light" else "#ecf7ff"};
  --muted: {"#5e6b82" if safe_theme == "light" else "#8fa3bf"};
  --faint: {"#8290a8" if safe_theme == "light" else "#61748f"};
  --border: {"rgba(98, 119, 154, .20)" if safe_theme == "light" else "rgba(139, 226, 255, .14)"};
  --border-strong: {"rgba(60, 95, 190, .24)" if safe_theme == "light" else "rgba(101, 229, 255, .28)"};
  --shadow: {"0 20px 60px rgba(46, 76, 140, .16)" if safe_theme == "light" else "0 20px 70px rgba(0, 0, 0, .40)"};
  --glow: {"0 0 36px rgba(92, 116, 255, .18)" if safe_theme == "light" else "0 0 44px rgba(39, 226, 255, .18)"};
  --accent: #23d5ff;
  --accent-2: #8b5cf6;
  --accent-3: #21e6a8;
  --warning: #fbbf24;
}}

html, body, [data-testid="stAppViewContainer"] {{
  color: var(--text) !important;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background:
    radial-gradient(circle at top left, {"rgba(82, 111, 255, .16)" if safe_theme == "light" else "rgba(16, 185, 255, .14)"}, transparent 34rem),
    radial-gradient(circle at 84% 4%, rgba(139, 92, 246, .14), transparent 30rem),
    linear-gradient(135deg, var(--bg), var(--bg-2)) !important;
}}

[data-testid="stHeader"], [data-testid="stToolbar"], footer {{ display: none !important; }}

.block-container {{
  max-width: 1180px !important;
  padding: 1rem 1.5rem 2rem !important;
}}

/* Dark-mode toggle pinned top-right, clear of the header. */
.st-key-mira_theme_toggle {{
  position: absolute;
  top: .3rem;
  right: .6rem;
  z-index: 6;
}}

/* ---- Header ------------------------------------------------------------- */

.cc-header {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  margin: .2rem 0 1.1rem;
}}

.brand {{ display: flex; gap: 13px; align-items: center; }}

.logo-mark {{
  width: 46px;
  height: 46px;
  border-radius: 15px;
  display: grid;
  place-items: center;
  font-weight: 900;
  letter-spacing: -.08em;
  color: #04111f;
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  box-shadow: 0 0 30px rgba(35, 213, 255, .34);
}}

.brand h1 {{ margin: 0; font-size: 1.5rem; letter-spacing: -.04em; }}
.muted {{ margin: 0; color: var(--muted); font-size: .82rem; }}

.header-right {{ display: flex; align-items: center; gap: 10px; }}

.top-pill {{
  display: inline-flex;
  align-items: center;
  padding: 7px 13px;
  border-radius: 999px;
  color: var(--accent);
  font-weight: 800;
  font-size: .78rem;
  letter-spacing: .04em;
  border: 1px solid var(--border);
  background: var(--panel-soft);
}}

.status-online {{
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: .74rem;
  font-weight: 800;
  color: var(--accent-3);
  letter-spacing: .08em;
}}

.pulse {{
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--accent-3);
  box-shadow: 0 0 18px var(--accent-3);
}}

.avatar {{
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  color: white;
  background: linear-gradient(135deg, var(--accent-2), var(--accent));
  font-size: .76rem;
  font-weight: 900;
}}

/* ---- Tabs (primary navigation) ------------------------------------------ */

.stTabs [data-baseweb="tab-list"] {{
  gap: 8px;
  padding: 6px;
  border-radius: var(--radius-lg);
  border: 1px solid var(--border);
  background: var(--panel);
  box-shadow: var(--shadow);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
}}

.stTabs [data-baseweb="tab-list"] {{ border-bottom: 1px solid var(--border); }}

.stTabs [data-baseweb="tab"] {{
  border-radius: 12px;
  padding: 8px 16px;
  color: var(--muted);
  font-weight: 650;
}}

.stTabs [data-baseweb="tab"]:hover {{ color: var(--text); }}

.stTabs [aria-selected="true"] {{
  color: var(--text) !important;
  background: linear-gradient(135deg, rgba(35, 213, 255, .16), rgba(139, 92, 246, .14));
  box-shadow: var(--glow);
}}

.stTabs [data-baseweb="tab-highlight"] {{ background: transparent; }}
.stTabs [data-baseweb="tab-panel"] {{ padding-top: 1.2rem; }}

/* ---- Section heads ------------------------------------------------------ */

.section-title {{
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 12px;
  margin-bottom: 1rem;
}}

.section-title h2 {{ margin: 0; font-size: 1.5rem; letter-spacing: -.03em; }}

/* ---- Native widgets ----------------------------------------------------- */

.stButton > button {{
  width: 100%;
  border-radius: 12px;
  padding: 9px 14px;
  font-weight: 650;
  color: var(--muted);
  border: 1px solid var(--border);
  background: var(--panel-soft);
  transition: transform .18s var(--ease), border-color .18s var(--ease), background .18s var(--ease), color .18s var(--ease);
}}

.stButton > button:hover {{
  transform: translateY(-1px);
  color: var(--text);
  border-color: var(--border-strong);
  background: linear-gradient(135deg, rgba(35, 213, 255, .14), rgba(139, 92, 246, .12));
}}

.st-key-send_message .stButton > button {{
  color: #04111f;
  font-weight: 850;
  border: none;
  background: linear-gradient(135deg, var(--accent), var(--accent-3));
  box-shadow: 0 14px 34px rgba(35, 213, 255, .24);
}}

.stTextInput input {{
  border-radius: 13px !important;
  border: 1px solid var(--border) !important;
  background: var(--panel-soft) !important;
  color: var(--text) !important;
}}
.stTextInput input::placeholder {{ color: var(--faint) !important; }}

[data-testid="stMetric"] {{
  border-radius: 14px;
  padding: 12px 14px;
  background: var(--panel-soft);
  border: 1px solid var(--border);
}}
[data-testid="stMetricLabel"] p {{ color: var(--faint) !important; font-size: .76rem; }}
[data-testid="stMetricValue"] {{ color: var(--text) !important; font-size: 1.3rem; }}

.stProgress > div > div > div {{
  background: linear-gradient(90deg, var(--accent), var(--accent-2)) !important;
}}

[data-testid="stCaptionContainer"], .stCaption {{ color: var(--muted) !important; }}
.stToggle label, .stToggle p {{ color: var(--muted) !important; }}

h2, h3, h4 {{ color: var(--text); letter-spacing: -.02em; }}

/* ---- Cards & fragments -------------------------------------------------- */

.badge {{
  color: var(--accent);
  font-size: .7rem;
  font-weight: 850;
  padding: 5px 10px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--panel-soft);
  letter-spacing: .07em;
  white-space: nowrap;
}}

.bubble {{
  border-radius: 18px;
  padding: 13px 16px;
  margin: 10px 0;
  max-width: 78%;
  line-height: 1.55;
  border: 1px solid var(--border);
  background: var(--panel-soft);
}}
.bubble.user {{
  margin-left: auto;
  background: linear-gradient(135deg, rgba(35, 213, 255, .18), rgba(139, 92, 246, .18));
}}

.brief-card {{
  margin: 1.2rem 0 .6rem;
  border-radius: var(--radius-lg);
  padding: 18px;
  background: linear-gradient(135deg, rgba(35, 213, 255, .10), rgba(139, 92, 246, .08));
  border: 1px solid var(--border-strong);
}}

.brief-head, .row-top {{
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
}}
.brief-head h3 {{ margin: 0 0 .15rem; font-size: 1.05rem; }}

.metric-tile {{
  padding: 13px;
  border-radius: 14px;
  background: var(--panel-soft);
  border: 1px solid var(--border);
}}
.metric-tile small {{ display: block; color: var(--faint); margin-bottom: 5px; font-size: .74rem; }}
.metric-tile strong {{ font-size: .98rem; }}

.chip-row {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }}
.chip {{
  display: inline-flex;
  align-items: center;
  color: var(--muted);
  padding: 6px 11px;
  font-size: .78rem;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--panel-soft);
}}

.graph-stage {{
  height: 320px;
  position: relative;
  border-radius: var(--radius-lg);
  margin-bottom: 1rem;
  background:
    radial-gradient(circle at 50% 48%, rgba(35, 213, 255, .18), transparent 11rem),
    linear-gradient(135deg, rgba(255,255,255,.035), transparent);
  border: 1px solid var(--border);
}}

.node {{
  position: absolute;
  display: grid;
  place-items: center;
  border-radius: 50%;
  border: 1px solid var(--border-strong);
  box-shadow: var(--glow);
  background: var(--panel-strong);
  color: var(--text);
  font-weight: 850;
  font-size: .84rem;
}}
.node.main {{ width: 92px; height: 92px; left: calc(50% - 46px); top: 104px; }}
.node.n1 {{ width: 58px; height: 58px; left: 12%; top: 50px; color: var(--accent); }}
.node.n2 {{ width: 54px; height: 54px; right: 14%; top: 56px; color: var(--accent-2); }}
.node.n3 {{ width: 52px; height: 52px; left: 20%; bottom: 42px; color: var(--accent-3); }}
.node.n4 {{ width: 62px; height: 62px; right: 18%; bottom: 34px; color: var(--warning); }}

.edge {{
  position: absolute;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--accent), transparent);
  opacity: .5;
  transform-origin: left center;
}}
.edge.e1 {{ width: 230px; left: 18%; top: 96px; transform: rotate(20deg); }}
.edge.e2 {{ width: 210px; right: 18%; top: 104px; transform: rotate(-18deg); }}
.edge.e3 {{ width: 190px; left: 24%; bottom: 92px; transform: rotate(-16deg); }}
.edge.e4 {{ width: 196px; right: 22%; bottom: 86px; transform: rotate(17deg); }}

.memory-row, .evidence-row, .reflection-card, .community-row, .timeline-card {{
  border-radius: 14px;
  padding: 14px;
  margin: 10px 0;
  background: var(--panel-soft);
  border: 1px solid var(--border);
}}
.memory-row strong, .evidence-row strong, .community-row strong {{ font-size: .95rem; }}
.reflection-card p {{ margin: .4rem 0 .55rem; font-size: .92rem; line-height: 1.55; }}
.evidence-row .muted, .community-row .muted, .memory-row .muted {{ font-size: .8rem; }}

.timeline-card {{ min-height: 104px; }}
.timeline-card h4 {{ margin: .45rem 0 0; font-size: .96rem; }}
</style>
"""
