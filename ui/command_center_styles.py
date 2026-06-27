# ruff: noqa: E501
"""Custom CSS for the MIRA Memory Command Center (Claude-style).

Ownership: Sarah.
Related issue: ISSUE-130.
Architecture area: UI.

Warm paper/charcoal palette with a coral accent. Themes the Claude-style left
rail, the workspace top bar (with the theme toggle that survives collapsing the
rail), native chat_message / chat_input, and the hand-written HTML fragments.
Theme variables live on a global scope so they cascade onto native widgets.
"""

from __future__ import annotations


def command_center_css(theme: str, *, rail_collapsed: bool = False) -> str:
    """Return the custom CSS layer for the selected theme."""
    safe_theme = "light" if theme == "light" else "dark"
    rail_width = "68px" if rail_collapsed else "272px"
    content_left_padding = "96px" if rail_collapsed else "304px"
    content_max_width = "980px" if rail_collapsed else "860px"
    return f"""
<style>
:root, [data-testid="stAppViewContainer"] {{
  --ease: cubic-bezier(.2,.8,.2,1);
  --bg: {"#f7f4ec" if safe_theme == "light" else "#262624"};
  --surface: {"#fffdf8" if safe_theme == "light" else "#30302e"};
  --surface-soft: {"#f1ede4" if safe_theme == "light" else "#393937"};
  --rail: {"#eee9de" if safe_theme == "light" else "#1f1e1d"};
  --user-bubble: {"#ebe5d8" if safe_theme == "light" else "#3a3a37"};
  --text: {"#28251f" if safe_theme == "light" else "#f3f2ec"};
  --muted: {"#645f55" if safe_theme == "light" else "#a3a299"};
  --faint: {"#8b8578" if safe_theme == "light" else "#7d7c73"};
  --border: {"#ddd5c7" if safe_theme == "light" else "#42423f"};
  --border-strong: {"#cfc4b2" if safe_theme == "light" else "#54534f"};
  --accent: {"#cc785c" if safe_theme == "light" else "#d97757"};
  --accent-soft: {"rgba(204, 120, 92, .13)" if safe_theme == "light" else "rgba(217, 119, 87, .17)"};
  --shadow: {"0 1px 3px rgba(50, 40, 30, .06), 0 8px 24px rgba(50, 40, 30, .05)" if safe_theme == "light" else "0 1px 3px rgba(0, 0, 0, .3)"};
}}

html, body, [data-testid="stAppViewContainer"] {{
  color: var(--text) !important;
  font-family: ui-sans-serif, -apple-system, "Segoe UI", Inter, system-ui, sans-serif;
  background: var(--bg) !important;
}}

/* Hide Streamlit chrome we don't use (no native sidebar, so no collapse). */
[data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stHeader"], footer {{ display: none !important; }}

/* Full-width app; the workspace clears the fixed rail via left padding. */
.block-container {{
  max-width: 100% !important;
  padding: 1.4rem 2rem 3rem {content_left_padding} !important;
  transition: padding .18s var(--ease);
}}
.st-key-cc_main {{ max-width: {content_max_width}; margin: 0 auto; }}

/* ---- Workspace top bar -------------------------------------------------- */

.topbar {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin: .1rem 0 1.4rem;
}}
.topbar-title {{ font-size: 1rem; font-weight: 600; color: var(--text); }}
.caret {{ color: var(--faint); font-size: .9rem; }}
.plan-pill {{
  font-size: .78rem;
  color: var(--muted);
  padding: 5px 12px;
  border-radius: 999px;
  border: 1px solid var(--border);
}}
.plan-pill b {{ color: var(--accent); font-weight: 600; }}
.disclaimer {{ text-align: center; color: var(--faint); font-size: .74rem; margin: .8rem 0 0; }}

/* ---- Navigation rail (always-visible left column) ----------------------- */

.st-key-cc_rail {{
  position: fixed;
  top: 0;
  left: 0;
  width: {rail_width};
  height: 100vh;
  overflow-y: auto;
  z-index: 100;
  background: var(--rail);
  border-right: 1px solid var(--border);
  padding: {"18px 10px" if rail_collapsed else "18px 14px"};
  transition: width .18s var(--ease), padding .18s var(--ease);
}}

/* Brand button (clickable wordmark that returns to the landing page). */
.st-key-home_brand {{ margin-bottom: .6rem; }}
.st-key-home_brand button {{
  justify-content: flex-start;
  border: none !important;
  background: transparent !important;
  box-shadow: none !important;
  color: var(--text) !important;
  font-weight: 700;
  font-size: 1.4rem;
  letter-spacing: -.02em;
  padding: .3rem .4rem;
}}
.st-key-home_brand button:hover {{ color: var(--accent) !important; }}

.st-key-home_brand_collapsed .stButton > button,
.st-key-rail_expand .stButton > button,
.st-key-rail_collapse .stButton > button,
.st-key-rail_theme_icon .stButton > button,
.st-key-nav_collapsed_Chat .stButton > button,
.st-key-nav_collapsed_Graph .stButton > button,
.st-key-nav_collapsed_Working_Set .stButton > button,
.st-key-nav_collapsed_Retrieval .stButton > button,
.st-key-nav_collapsed_Reflections .stButton > button,
.st-key-nav_collapsed_Communities .stButton > button,
.st-key-nav_collapsed_Timeline .stButton > button {{
  justify-content: center !important;
  text-align: center !important;
  width: 44px !important;
  min-width: 44px !important;
  height: 42px !important;
  padding: 0 !important;
  margin: 0 auto 6px !important;
  border-radius: 13px !important;
}}
.st-key-rail_collapse .stButton > button {{
  justify-content: center !important;
  padding: 6px !important;
}}

.rail-section {{
  margin: 1.1rem .35rem .35rem;
  color: var(--faint);
  font-size: .7rem;
  font-weight: 700;
  letter-spacing: .07em;
  text-transform: uppercase;
}}

.rail-divider {{ height: 1px; background: var(--border); margin: 1.1rem .2rem .8rem; }}
.rail-user {{ display: flex; align-items: center; gap: 10px; padding: 0 .2rem .6rem; }}
.rail-user-meta {{ display: flex; flex-direction: column; line-height: 1.25; }}
.rail-user-meta strong {{ font-size: .9rem; }}
.rail-user-meta small {{ color: var(--faint); font-size: .74rem; }}

.avatar {{
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  color: #fff;
  background: linear-gradient(135deg, var(--accent), #b5614a);
  font-size: .76rem;
  font-weight: 800;
}}

/* New-conversation button (outlined) + nav buttons (quiet list). */
.st-key-new_chat .stButton > button {{
  justify-content: flex-start;
  text-align: left;
  border: 1px solid var(--border-strong);
  background: var(--surface);
  color: var(--text);
  font-weight: 600;
  border-radius: 11px;
}}
.st-key-new_chat .stButton > button:hover {{ border-color: var(--accent); color: var(--accent); }}

.st-key-history_nova .stButton > button,
.st-key-history_roadmap .stButton > button,
.st-key-history_benchmarks .stButton > button,
.st-key-history_kelechi .stButton > button {{
  min-height: 44px;
  align-items: flex-start;
  white-space: pre-line;
  line-height: 1.25;
  font-size: .82rem;
}}
.st-key-history_nova .stButton > button[kind="primary"],
.st-key-history_roadmap .stButton > button[kind="primary"],
.st-key-history_benchmarks .stButton > button[kind="primary"],
.st-key-history_kelechi .stButton > button[kind="primary"],
.st-key-history_nova [data-testid="stBaseButton-primary"],
.st-key-history_roadmap [data-testid="stBaseButton-primary"],
.st-key-history_benchmarks [data-testid="stBaseButton-primary"],
.st-key-history_kelechi [data-testid="stBaseButton-primary"] {{
  border: 1px solid var(--border);
  background: var(--accent-soft);
  color: var(--text);
}}

.st-key-cc_rail .stButton > button {{
  justify-content: flex-start;
  text-align: left;
  border: none;
  background: transparent;
  color: var(--muted);
  font-weight: 500;
  border-radius: 9px;
  padding: 8px 12px;
}}
.st-key-cc_rail .stButton > button:hover {{
  background: {"rgba(0,0,0,.04)" if safe_theme == "light" else "rgba(255,255,255,.05)"};
  color: var(--text);
}}
.st-key-cc_rail .stButton > button[kind="primary"],
.st-key-cc_rail [data-testid="stBaseButton-primary"] {{
  background: var(--accent-soft);
  color: var(--text);
  font-weight: 600;
}}

/* Theme toggle in the rail footer. */
.st-key-mira_theme_toggle {{ padding: .4rem .2rem 0; }}

/* ---- Chat (native chat_message / chat_input) ---------------------------- */

.turn {{ display: flex; gap: 12px; margin: 1.3rem 0; }}
.turn.user {{ justify-content: flex-end; }}
.turn.bot {{ align-items: flex-start; }}

.ubub {{
  background: var(--user-bubble);
  color: var(--text);
  border-radius: 16px;
  padding: 11px 16px;
  max-width: 76%;
  line-height: 1.6;
  font-size: .98rem;
}}

.bot-ava {{
  flex: 0 0 28px;
  width: 28px;
  height: 28px;
  margin-top: 2px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  color: var(--accent);
  background: var(--accent-soft);
  font-size: .95rem;
}}
.bot-msg {{ color: var(--text); line-height: 1.72; font-size: 1rem; max-width: 88%; }}
.bot-msg-wide {{ max-width: 100%; width: 100%; }}

.empty-chat-card {{
  margin: 4rem auto 2rem;
  max-width: 520px;
  text-align: center;
  border: 1px solid var(--border);
  border-radius: 22px;
  background: var(--surface);
  padding: 28px;
  box-shadow: var(--shadow);
}}
.empty-chat-card strong {{
  display: block;
  color: var(--text);
  font-size: 1.12rem;
  margin-bottom: 8px;
}}
.empty-chat-card p {{
  margin: 0;
  color: var(--muted);
  line-height: 1.55;
}}

.chat-mode-row {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: .4rem 0 1rem;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: var(--surface);
}}

.tile-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 10px;
  margin-top: 14px;
}}

/* Inline composer (rounded box: borderless input + round coral send). */
.st-key-cc_composer {{
  margin-top: .6rem;
  border: 1px solid var(--border-strong);
  border-radius: 26px;
  padding: 4px 6px 4px 10px;
  background: {"#f8f6ef" if safe_theme == "light" else "#242321"};
  box-shadow: var(--shadow);
}}
.st-key-cc_composer:focus-within {{ border-color: var(--accent); }}
.st-key-cc_composer [data-testid="stTextInputRoot"],
.st-key-cc_composer [data-baseweb="input"],
.st-key-cc_composer [data-baseweb="base-input"] {{
  border: none !important;
  background: transparent !important;
  box-shadow: none !important;
}}
.st-key-cc_composer [data-baseweb="input"]:focus-within {{
  border: none !important;
  outline: none !important;
  box-shadow: none !important;
}}
.st-key-cc_composer .stTextInput input {{
  border: none !important;
  background: transparent !important;
  color: var(--text) !important;
  font-size: .98rem !important;
  padding: 11px 8px !important;
  caret-color: var(--accent) !important;
}}
.st-key-cc_composer .stTextInput input::placeholder {{ color: var(--faint) !important; }}
.st-key-composer_add {{ display: flex; justify-content: center; }}
.st-key-composer_add .stButton > button {{
  width: 38px;
  min-width: 38px;
  height: 38px;
  border-radius: 50%;
  padding: 0;
  color: var(--muted);
  border: 1px solid var(--border);
  background: transparent;
}}
.st-key-composer_add .stButton > button:hover {{ color: var(--text); border-color: var(--border-strong); }}

.st-key-send_message {{ display: flex; justify-content: center; }}
.st-key-send_message .stButton > button {{
  width: 38px;
  min-width: 38px;
  height: 38px;
  border-radius: 50%;
  padding: 0;
  color: #fff;
  border: none;
  background: var(--accent);
}}
.st-key-send_message .stButton > button:hover {{ color: #fff; background: var(--accent); filter: brightness(1.05); }}

.suggest-label {{
  margin: 1.4rem 0 .5rem;
  color: var(--faint);
  font-size: .74rem;
  font-weight: 600;
  letter-spacing: .04em;
  text-transform: uppercase;
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
.stButton > button:hover {{ color: var(--text); border-color: var(--border-strong); background: var(--surface-soft); }}

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
.stToggle label, .stToggle p, [data-testid="stWidgetLabel"] p {{ color: var(--muted) !important; }}

/* Readable bold text inside cards/turns (overrides Streamlit defaults). */
.bot-msg strong, .brief-card strong, .row-card strong, .row-top strong, .topbar-title {{ color: var(--text); }}

/* ---- Section heads & cards ---------------------------------------------- */

.section-title {{ margin-bottom: 1.2rem; }}
.section-title h2 {{ margin: 0 0 .2rem; font-size: 1.5rem; letter-spacing: -.02em; font-family: Georgia, "Times New Roman", serif; }}
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

.tile {{
  padding: 12px 13px;
  border-radius: 13px;
  background: var(--surface-soft);
  border: 1px solid var(--border);
}}
.tile small {{ display: block; color: var(--faint); margin-bottom: 5px; font-size: .74rem; }}
.tile strong {{ display: block; font-size: .94rem; color: var(--text); line-height: 1.35; }}

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

.muted {{ margin: 0; color: var(--muted); font-size: .85rem; }}
</style>
"""
