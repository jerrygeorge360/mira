# ruff: noqa: E501
"""Custom CSS for the MIRA Memory Command Center (Claude-style).

Ownership: Sarah.
Related issue: ISSUE-130.
Architecture area: UI.

Warm paper/charcoal palette with a coral accent, a centered single column, a
serif greeting, understated underline tabs, and a rounded composer — inspired by
the Claude UI. Theme variables live on a global scope so they cascade onto native
Streamlit widgets, not just the hand-written HTML fragments.
"""

from __future__ import annotations


def command_center_css(theme: str) -> str:
    """Return the custom CSS layer for the selected theme."""
    safe_theme = "light" if theme == "light" else "dark"
    return f"""
<style>
:root, [data-testid="stAppViewContainer"] {{
  --ease: cubic-bezier(.2,.8,.2,1);
  --bg: {"#f4f3ee" if safe_theme == "light" else "#262624"};
  --surface: {"#ffffff" if safe_theme == "light" else "#30302e"};
  --surface-soft: {"#faf9f5" if safe_theme == "light" else "#393937"};
  --user-bubble: {"#ecebe3" if safe_theme == "light" else "#3a3a37"};
  --text: {"#2d2c28" if safe_theme == "light" else "#f3f2ec"};
  --muted: {"#6b6a62" if safe_theme == "light" else "#a3a299"};
  --faint: {"#908f86" if safe_theme == "light" else "#7d7c73"};
  --border: {"#e6e4da" if safe_theme == "light" else "#42423f"};
  --border-strong: {"#d6d3c6" if safe_theme == "light" else "#54534f"};
  --accent: {"#cc785c" if safe_theme == "light" else "#d97757"};
  --accent-soft: {"rgba(204, 120, 92, .12)" if safe_theme == "light" else "rgba(217, 119, 87, .16)"};
  --shadow: {"0 1px 3px rgba(50, 40, 30, .06), 0 8px 24px rgba(50, 40, 30, .05)" if safe_theme == "light" else "0 1px 3px rgba(0, 0, 0, .3)"};
}}

html, body, [data-testid="stAppViewContainer"] {{
  color: var(--text) !important;
  font-family: ui-sans-serif, -apple-system, "Segoe UI", Inter, system-ui, sans-serif;
  background: var(--bg) !important;
}}

/* Hide the deploy toolbar/decoration, but keep the header so the sidebar
   expand control stays clickable when the rail is collapsed. */
[data-testid="stToolbar"], [data-testid="stDecoration"], footer {{ display: none !important; }}
[data-testid="stHeader"] {{ background: transparent !important; }}
[data-testid="stSidebarCollapsedControl"] {{ display: flex !important; }}
[data-testid="stSidebarCollapseButton"] {{ display: inline-flex !important; }}

.block-container {{
  max-width: 880px !important;
  padding: 2rem 1.5rem 3rem !important;
}}

/* ---- Sidebar rail (view navigation) ------------------------------------- */

[data-testid="stSidebar"] {{
  background: {"#ebe9e0" if safe_theme == "light" else "#1f1e1d"} !important;
  border-right: 1px solid var(--border);
}}
[data-testid="stSidebar"] > div {{ padding-top: 1.4rem; }}

.brand {{ display: flex; gap: 9px; align-items: baseline; padding: 0 .25rem; }}
.spark {{ color: var(--accent); font-size: 1.05rem; line-height: 1; }}
.spark-lg {{ color: var(--accent); font-size: 1.6rem; line-height: 1; }}
.wordmark {{ font-weight: 700; font-size: 1.25rem; letter-spacing: -.01em; }}
.muted {{ margin: 0; color: var(--muted); font-size: .85rem; }}
.sb-tagline {{ margin: .15rem .25rem 1.2rem; color: var(--faint); font-size: .76rem; }}
.sb-divider {{ height: 1px; background: var(--border); margin: 1rem .25rem; }}

/* Sidebar nav buttons read as a quiet list; the active one is coral-tinted. */
[data-testid="stSidebar"] .stButton > button {{
  justify-content: flex-start;
  text-align: left;
  border: none;
  background: transparent;
  color: var(--muted);
  font-weight: 500;
  border-radius: 10px;
  padding: 9px 12px;
}}
[data-testid="stSidebar"] .stButton > button:hover {{
  background: {"rgba(0,0,0,.04)" if safe_theme == "light" else "rgba(255,255,255,.05)"};
  color: var(--text);
}}
[data-testid="stSidebar"] .stButton > button[kind="primary"],
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] {{
  background: var(--accent-soft);
  color: var(--text);
  font-weight: 600;
}}

/* Theme toggle sits in the sidebar footer. */
.st-key-mira_theme_toggle {{ padding: 0 .25rem; }}

/* ---- Chat --------------------------------------------------------------- */

.greeting {{
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 1.2rem 0 2rem;
  font-family: Georgia, "Times New Roman", serif;
  font-size: 1.9rem;
  letter-spacing: -.01em;
  color: var(--text);
}}

.turn {{ display: flex; margin: 1.1rem 0; }}
.turn.user {{ justify-content: flex-end; }}
.turn.assistant {{ gap: 11px; align-items: flex-start; }}
.turn.assistant .spark {{ margin-top: 3px; font-size: 1rem; }}

.bubble {{
  background: var(--user-bubble);
  border-radius: 16px;
  padding: 11px 16px;
  max-width: 80%;
  line-height: 1.6;
  font-size: .96rem;
}}

.answer {{
  line-height: 1.7;
  font-size: 1rem;
  color: var(--text);
  max-width: 92%;
}}

/* ---- Suggested follow-ups + composer ------------------------------------ */

.suggest-label {{
  margin: 1.6rem 0 .5rem;
  color: var(--faint);
  font-size: .76rem;
  font-weight: 600;
  letter-spacing: .04em;
  text-transform: uppercase;
}}

.st-key-cc_composer {{
  margin-top: 1rem;
  border: 1px solid var(--border-strong);
  border-radius: 26px;
  padding: 4px 6px 4px 10px;
  background: var(--surface);
  box-shadow: var(--shadow);
}}
.st-key-cc_composer:focus-within {{ border-color: var(--accent); }}

.st-key-cc_composer .stTextInput input {{
  border: none !important;
  background: transparent !important;
  color: var(--text) !important;
  font-size: .98rem !important;
  padding: 11px 8px !important;
}}
.st-key-cc_composer .stTextInput input::placeholder {{ color: var(--faint) !important; }}

/* Round coral send button, centered in its narrow column. */
.st-key-send_message {{ display: flex; justify-content: center; }}
.st-key-send_message .stButton > button {{
  width: 40px;
  min-width: 40px;
  height: 40px;
  border-radius: 50%;
  padding: 0;
  font-size: 1.15rem;
  font-weight: 700;
  line-height: 1;
  color: #ffffff;
  border: none;
  background: var(--accent);
}}
.st-key-send_message .stButton > button:hover {{
  color: #ffffff;
  background: var(--accent);
  filter: brightness(1.05);
  transform: none;
}}

/* ---- Native widgets ----------------------------------------------------- */

.stButton > button {{
  width: 100%;
  border-radius: 11px;
  padding: 8px 13px;
  font-weight: 500;
  font-size: .86rem;
  color: var(--muted);
  border: 1px solid var(--border);
  background: var(--surface);
  transition: background .16s var(--ease), color .16s var(--ease), border-color .16s var(--ease);
}}
.stButton > button:hover {{
  color: var(--text);
  border-color: var(--border-strong);
  background: var(--surface-soft);
}}

.stTextInput input {{
  border-radius: 12px !important;
  border: 1px solid var(--border) !important;
  background: var(--surface) !important;
  color: var(--text) !important;
}}
.stTextInput input::placeholder {{ color: var(--faint) !important; }}

[data-testid="stMetric"] {{
  border-radius: 14px;
  padding: 13px 15px;
  background: var(--surface);
  border: 1px solid var(--border);
}}
[data-testid="stMetricLabel"] p {{ color: var(--faint) !important; font-size: .76rem; }}
[data-testid="stMetricValue"] {{ color: var(--text) !important; font-size: 1.3rem; }}

.stProgress > div > div > div {{ background: var(--accent) !important; }}

[data-testid="stCaptionContainer"], .stCaption {{ color: var(--faint) !important; }}
.stToggle label, .stToggle p {{ color: var(--muted) !important; }}

/* ---- Section heads & cards ---------------------------------------------- */

.section-title {{ margin-bottom: 1.2rem; }}
.section-title h2 {{ margin: 0 0 .2rem; font-size: 1.5rem; letter-spacing: -.02em; color: var(--text); font-family: Georgia, "Times New Roman", serif; }}

h2, h3, h4 {{ color: var(--text); }}

.badge {{
  color: var(--accent);
  font-size: .72rem;
  font-weight: 600;
  padding: 3px 9px;
  border-radius: 999px;
  background: var(--accent-soft);
  white-space: nowrap;
}}

.brief-card {{
  margin: 1.4rem 0 .7rem;
  border-radius: 16px;
  padding: 16px 18px;
  background: var(--surface);
  border: 1px solid var(--border);
  box-shadow: var(--shadow);
}}
.brief-head {{ display: flex; justify-content: space-between; align-items: center; gap: 10px; }}
.brief-head h3 {{ margin: 0; font-size: 1.05rem; }}
.brief-card .muted {{ margin-top: .35rem; }}

.tile {{
  padding: 13px;
  border-radius: 13px;
  background: var(--surface-soft);
  border: 1px solid var(--border);
}}
.tile small {{ display: block; color: var(--faint); margin-bottom: 5px; font-size: .74rem; }}
.tile strong {{ font-size: .96rem; }}

.row-card {{
  border-radius: 14px;
  padding: 14px 16px;
  margin: 10px 0;
  background: var(--surface);
  border: 1px solid var(--border);
}}
.row-card strong {{ font-size: .95rem; }}
.row-card p {{ margin: .4rem 0 .55rem; font-size: .93rem; line-height: 1.6; color: var(--text); }}
.row-card .muted {{ font-size: .82rem; }}
.row-top {{ display: flex; justify-content: space-between; gap: 10px; align-items: center; }}

.chip-row {{ display: flex; flex-wrap: wrap; gap: 7px; margin-top: 10px; }}
.chip {{
  display: inline-flex;
  align-items: center;
  color: var(--muted);
  padding: 5px 11px;
  font-size: .78rem;
  border-radius: 999px;
  background: var(--surface-soft);
  border: 1px solid var(--border);
}}

.timeline-card {{ min-height: 100px; }}
.timeline-card h4 {{ margin: .4rem 0 0; font-size: .94rem; }}

/* ---- Graph -------------------------------------------------------------- */

.graph-stage {{
  height: 320px;
  position: relative;
  border-radius: 16px;
  margin-bottom: 1rem;
  background:
    radial-gradient(circle at 50% 46%, var(--accent-soft), transparent 12rem),
    var(--surface);
  border: 1px solid var(--border);
}}

.node {{
  position: absolute;
  display: grid;
  place-items: center;
  border-radius: 50%;
  border: 1px solid var(--border-strong);
  background: var(--surface);
  color: var(--text);
  font-weight: 600;
  font-size: .82rem;
  box-shadow: var(--shadow);
}}
.node.main {{ width: 88px; height: 88px; left: calc(50% - 44px); top: 108px; color: var(--accent); border-color: var(--accent); }}
.node.n1 {{ width: 56px; height: 56px; left: 13%; top: 54px; }}
.node.n2 {{ width: 52px; height: 52px; right: 15%; top: 60px; }}
.node.n3 {{ width: 50px; height: 50px; left: 21%; bottom: 44px; }}
.node.n4 {{ width: 58px; height: 58px; right: 19%; bottom: 36px; }}

.edge {{
  position: absolute;
  height: 1px;
  background: var(--border-strong);
  opacity: .8;
  transform-origin: left center;
}}
.edge.e1 {{ width: 220px; left: 19%; top: 100px; transform: rotate(20deg); }}
.edge.e2 {{ width: 200px; right: 19%; top: 108px; transform: rotate(-18deg); }}
.edge.e3 {{ width: 184px; left: 25%; bottom: 94px; transform: rotate(-16deg); }}
.edge.e4 {{ width: 190px; right: 23%; bottom: 88px; transform: rotate(17deg); }}
</style>
"""
