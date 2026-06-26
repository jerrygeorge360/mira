# ruff: noqa: E501
"""Custom CSS for the MIRA Memory Command Center.

Ownership: Sarah.
Related issue: ISSUE-130.
Architecture area: UI.

The renderer (``ui/command_center.py``) builds the layout from native Streamlit
columns/containers, so this stylesheet themes two things: the keyed card
containers (``.st-key-cc_*``) and the native widgets (buttons, tabs, inputs,
metrics) that live inside them. Theme variables are attached to a global scope
so they cascade onto native widgets, not just the hand-written HTML fragments.
"""

from __future__ import annotations


def command_center_css(theme: str) -> str:
    """Return the custom CSS layer for the selected theme."""
    safe_theme = "light" if theme == "light" else "dark"
    return f"""
<style>
:root, [data-testid="stAppViewContainer"] {{
  --radius-xl: 26px;
  --radius-lg: 20px;
  --radius-md: 15px;
  --radius-sm: 11px;
  --ease: cubic-bezier(.2,.8,.2,1);
  --bg: {"#eef3fb" if safe_theme == "light" else "#050812"};
  --bg-2: {"#f8fbff" if safe_theme == "light" else "#09111f"};
  --panel: {"rgba(255,255,255,.78)" if safe_theme == "light" else "rgba(13, 22, 38, .80)"};
  --panel-strong: {"rgba(255,255,255,.94)" if safe_theme == "light" else "rgba(18, 30, 52, .94)"};
  --panel-soft: {"rgba(239,246,255,.84)" if safe_theme == "light" else "rgba(10, 18, 32, .60)"};
  --text: {"#111827" if safe_theme == "light" else "#ecf7ff"};
  --muted: {"#5e6b82" if safe_theme == "light" else "#8fa3bf"};
  --faint: {"#8290a8" if safe_theme == "light" else "#61748f"};
  --border: {"rgba(98, 119, 154, .20)" if safe_theme == "light" else "rgba(139, 226, 255, .14)"};
  --border-strong: {"rgba(60, 95, 190, .24)" if safe_theme == "light" else "rgba(101, 229, 255, .28)"};
  --shadow: {"0 22px 70px rgba(46, 76, 140, .18)" if safe_theme == "light" else "0 22px 90px rgba(0, 0, 0, .42)"};
  --glow: {"0 0 36px rgba(92, 116, 255, .18)" if safe_theme == "light" else "0 0 44px rgba(39, 226, 255, .18)"};
  --accent: #23d5ff;
  --accent-2: #8b5cf6;
  --accent-3: #21e6a8;
  --warning: #fbbf24;
  --danger: #fb7185;
}}

html, body, [data-testid="stAppViewContainer"] {{
  color: var(--text) !important;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background:
    radial-gradient(circle at top left, {"rgba(82, 111, 255, .18)" if safe_theme == "light" else "rgba(16, 185, 255, .16)"}, transparent 32rem),
    radial-gradient(circle at 82% 8%, rgba(139, 92, 246, .15), transparent 28rem),
    linear-gradient(135deg, var(--bg), var(--bg-2)) !important;
}}

[data-testid="stHeader"], [data-testid="stToolbar"], footer {{
  display: none !important;
}}

.block-container {{
  max-width: 100% !important;
  padding: 1.1rem 1.4rem 1.6rem !important;
}}

/* The dark-mode toggle sits flush in the top-right corner. */
.st-key-mira_theme_toggle {{
  position: absolute;
  top: .2rem;
  right: .6rem;
  z-index: 5;
}}

/* ---- Card containers (keyed st.container -> .st-key-cc_*) ---------------- */

.st-key-cc_sidebar,
.st-key-cc_topbar,
.st-key-cc_chat,
.st-key-cc_brief,
[class*="st-key-cc_panel"],
.st-key-cc_timeline {{
  position: relative;
  border-radius: var(--radius-xl);
  padding: 20px;
  background:
    linear-gradient(145deg, rgba(255,255,255,.09), rgba(255,255,255,.02)),
    var(--panel);
  border: 1px solid var(--border);
  box-shadow: var(--shadow);
  backdrop-filter: blur(22px);
  -webkit-backdrop-filter: blur(22px);
}}

.st-key-cc_sidebar {{
  min-height: calc(100vh - 2.6rem);
}}

.st-key-cc_topbar {{
  padding: 12px 16px;
  border-radius: var(--radius-lg);
  margin-bottom: 16px;
}}

[class*="st-key-cc_panel"] {{
  min-height: 460px;
}}

.st-key-cc_brief {{
  margin: 12px 0;
  background: linear-gradient(135deg, rgba(35, 213, 255, .10), rgba(139, 92, 246, .08));
  border: 1px solid var(--border-strong);
}}

.st-key-cc_timeline {{
  margin-top: 16px;
}}

/* ---- Branding & sidebar ------------------------------------------------- */

.brand {{
  display: flex;
  gap: 13px;
  align-items: center;
  margin-bottom: 18px;
}}

.logo-mark {{
  width: 46px;
  height: 46px;
  border-radius: 16px;
  display: grid;
  place-items: center;
  font-weight: 900;
  letter-spacing: -.08em;
  color: #04111f;
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  box-shadow: 0 0 30px rgba(35, 213, 255, .34);
}}

.brand h1 {{ margin: 0; font-size: 1.45rem; letter-spacing: -.04em; }}
.brand p, .muted {{ margin: 0; color: var(--muted); font-size: .82rem; }}

.status-card {{
  border-radius: 18px;
  padding: 14px;
  margin: 14px 0 10px;
  background: var(--panel-soft);
  border: 1px solid var(--border);
}}

.status-online {{
  display: inline-flex;
  align-items: center;
  gap: 8px;
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

/* ---- Native buttons ----------------------------------------------------- */

.stButton > button {{
  width: 100%;
  border-radius: 14px;
  padding: 10px 14px;
  font-weight: 650;
  color: var(--text);
  border: 1px solid var(--border);
  background: var(--panel-soft);
  transition: transform .18s var(--ease), border-color .18s var(--ease), background .18s var(--ease);
}}

.stButton > button:hover {{
  transform: translateY(-1px);
  border-color: var(--border-strong);
  background: linear-gradient(135deg, rgba(35, 213, 255, .14), rgba(139, 92, 246, .12));
  color: var(--text);
}}

/* Sidebar nav buttons read as a left-aligned nav stack. */
[class*="st-key-nav_"] .stButton > button {{
  justify-content: flex-start;
  text-align: left;
  color: var(--muted);
}}

/* Accent call-to-action buttons. */
.st-key-optimize_memory .stButton > button,
.st-key-send_message .stButton > button {{
  color: #04111f;
  font-weight: 850;
  border: none;
  background: linear-gradient(135deg, var(--accent), var(--accent-3));
  box-shadow: 0 14px 34px rgba(35, 213, 255, .24);
}}

[class*="st-key-action_"] .stButton > button {{
  border-radius: 999px;
  font-size: .82rem;
  color: var(--muted);
}}

/* ---- Native tabs -------------------------------------------------------- */

.stTabs [data-baseweb="tab-list"] {{
  gap: 6px;
  border-bottom: 1px solid var(--border);
}}

.stTabs [data-baseweb="tab"] {{
  border-radius: 12px 12px 0 0;
  padding: 6px 12px;
  color: var(--muted);
  font-weight: 600;
}}

.stTabs [aria-selected="true"] {{
  color: var(--text);
  background: linear-gradient(135deg, rgba(35, 213, 255, .14), rgba(139, 92, 246, .12));
}}

.stTabs [data-baseweb="tab-highlight"] {{ background: var(--accent); }}

/* ---- Native inputs, metrics, progress, captions ------------------------- */

.stTextInput input {{
  border-radius: 14px !important;
  border: 1px solid var(--border) !important;
  background: var(--panel-soft) !important;
  color: var(--text) !important;
}}

.stTextInput input::placeholder {{ color: var(--faint) !important; }}

[data-testid="stMetric"] {{
  border-radius: 15px;
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

/* ---- Hand-written inner fragments --------------------------------------- */

.panel-title, .chat-title, .brief-head {{
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: start;
  margin-bottom: 12px;
}}

.panel-title h3, .brief-head h3 {{ margin: 0; font-size: 1.02rem; letter-spacing: -.03em; }}
.chat-title h2 {{ margin: 0; font-size: 1.7rem; letter-spacing: -.04em; }}

.badge {{
  color: var(--accent);
  font-size: .7rem;
  font-weight: 850;
  padding: 5px 9px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--panel-soft);
  letter-spacing: .07em;
}}

.top-pill {{
  display: inline-flex;
  align-items: center;
  height: 100%;
  padding: 8px 14px;
  border-radius: 999px;
  color: var(--accent);
  font-weight: 800;
  letter-spacing: .04em;
  border: 1px solid var(--border);
  background: var(--panel-soft);
}}

.profile-row {{
  display: flex;
  gap: 10px;
  align-items: center;
  justify-content: flex-end;
  height: 100%;
}}

.avatar {{
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  color: white;
  background: linear-gradient(135deg, var(--accent-2), var(--accent));
  font-size: .76rem;
  font-weight: 900;
}}

.bubble {{
  border-radius: 20px;
  padding: 13px 15px;
  margin: 8px 0;
  max-width: 88%;
  line-height: 1.55;
  border: 1px solid var(--border);
}}

.bubble.user {{
  margin-left: auto;
  background: linear-gradient(135deg, rgba(35, 213, 255, .18), rgba(139, 92, 246, .18));
}}

.bubble.assistant {{ background: var(--panel-soft); }}

.metric-grid {{
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}}

.metric-tile {{
  padding: 11px;
  border-radius: 15px;
  background: rgba(127, 145, 172, .08);
  border: 1px solid var(--border);
}}

.metric-tile small {{ display: block; color: var(--faint); margin-bottom: 4px; font-size: .74rem; }}
.metric-tile strong {{ font-size: .92rem; }}

.chip-row {{
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}}

.chip {{
  display: inline-flex;
  align-items: center;
  color: var(--muted);
  padding: 7px 11px;
  font-size: .78rem;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--panel-soft);
}}

.graph-stage {{
  height: 210px;
  position: relative;
  border-radius: 20px;
  margin-bottom: 12px;
  background:
    radial-gradient(circle at 50% 50%, rgba(35, 213, 255, .18), transparent 8rem),
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
  font-size: .82rem;
}}

.node.main {{ width: 78px; height: 78px; left: calc(50% - 39px); top: 64px; }}
.node.n1 {{ width: 50px; height: 50px; left: 26px; top: 32px; color: var(--accent); }}
.node.n2 {{ width: 46px; height: 46px; right: 32px; top: 34px; color: var(--accent-2); }}
.node.n3 {{ width: 44px; height: 44px; left: 56px; bottom: 28px; color: var(--accent-3); }}
.node.n4 {{ width: 54px; height: 54px; right: 48px; bottom: 20px; color: var(--warning); }}

.edge {{
  position: absolute;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--accent), transparent);
  opacity: .55;
  transform-origin: left center;
}}
.edge.e1 {{ width: 145px; left: 76px; top: 74px; transform: rotate(22deg); }}
.edge.e2 {{ width: 132px; right: 78px; top: 80px; transform: rotate(-20deg); }}
.edge.e3 {{ width: 120px; left: 94px; bottom: 70px; transform: rotate(-18deg); }}
.edge.e4 {{ width: 122px; right: 96px; bottom: 70px; transform: rotate(19deg); }}

.memory-row, .evidence-row, .reflection-card, .community-row, .timeline-card {{
  border-radius: 15px;
  padding: 12px;
  margin: 8px 0;
  background: var(--panel-soft);
  border: 1px solid var(--border);
}}

.memory-row strong, .evidence-row strong, .community-row strong {{ font-size: .92rem; }}
.reflection-card p {{ margin: .35rem 0 .5rem; font-size: .9rem; line-height: 1.5; }}
.evidence-row .muted, .community-row .muted, .memory-row .muted {{ font-size: .78rem; }}

.row-top {{
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
}}

.timeline-card {{ min-height: 96px; }}
.timeline-card h4 {{ margin: .4rem 0 0; font-size: .94rem; }}

@media (max-width: 1180px) {{
  [class*="st-key-cc_panel"] {{ min-height: auto; }}
  .st-key-cc_sidebar {{ min-height: auto; }}
}}
</style>
"""
