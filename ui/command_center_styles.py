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
  --rail: {"#ebe9e0" if safe_theme == "light" else "#1f1e1d"};
  --user-bubble: {"#ecebe3" if safe_theme == "light" else "#3a3a37"};
  --text: {"#2d2c28" if safe_theme == "light" else "#f3f2ec"};
  --muted: {"#6b6a62" if safe_theme == "light" else "#a3a299"};
  --faint: {"#908f86" if safe_theme == "light" else "#7d7c73"};
  --border: {"#e6e4da" if safe_theme == "light" else "#42423f"};
  --border-strong: {"#d6d3c6" if safe_theme == "light" else "#54534f"};
  --accent: {"#cc785c" if safe_theme == "light" else "#d97757"};
  --accent-soft: {"rgba(204, 120, 92, .13)" if safe_theme == "light" else "rgba(217, 119, 87, .17)"};
  --shadow: {"0 1px 3px rgba(50, 40, 30, .06), 0 8px 24px rgba(50, 40, 30, .05)" if safe_theme == "light" else "0 1px 3px rgba(0, 0, 0, .3)"};
}}

html, body, [data-testid="stAppViewContainer"] {{
  color: var(--text) !important;
  font-family: ui-sans-serif, -apple-system, "Segoe UI", Inter, system-ui, sans-serif;
  background: var(--bg) !important;
}}

/* Hide deploy toolbar/decoration; keep header so collapse controls survive. */
[data-testid="stToolbar"], [data-testid="stDecoration"], footer {{ display: none !important; }}
[data-testid="stHeader"] {{ background: transparent !important; }}

/* Sidebar collapse + the expand button shown when the rail is collapsed.
   Streamlit paints the expand icon as faded text (near-invisible on a custom
   theme), so force a clear coral chevron and pin the expand button. */
[data-testid="stSidebarCollapseButton"],
[data-testid="stExpandSidebarButton"] {{
  display: inline-flex !important;
  visibility: visible !important;
  opacity: 1 !important;
}}
[data-testid="stExpandSidebarButton"] {{
  position: fixed;
  top: .55rem;
  left: .55rem;
  z-index: 1000;
  background: var(--surface) !important;
  border: 1px solid var(--border-strong) !important;
  border-radius: 10px !important;
  box-shadow: var(--shadow);
}}
[data-testid="stSidebarCollapseButton"] button, [data-testid="stSidebarCollapseButton"] span,
[data-testid="stExpandSidebarButton"] button, [data-testid="stExpandSidebarButton"] span {{
  color: var(--accent) !important;
}}

.block-container {{
  max-width: 880px !important;
  padding: 1.4rem 1.5rem 7rem !important;
}}

/* ---- Workspace top bar -------------------------------------------------- */

.page-title {{
  font-size: 1.02rem;
  font-weight: 600;
  color: var(--muted);
  letter-spacing: -.01em;
}}
.st-key-mira_theme_toggle {{ display: flex; justify-content: flex-end; }}

/* ---- Sidebar rail ------------------------------------------------------- */

[data-testid="stSidebar"] {{
  background: var(--rail) !important;
  border-right: 1px solid var(--border);
}}
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {{ padding-top: .5rem; }}

.sb-brand {{ display: flex; gap: 9px; align-items: baseline; padding: .2rem .3rem 1rem; }}
.spark {{ color: var(--accent); font-size: 1.05rem; line-height: 1; }}
.spark-lg {{ color: var(--accent); font-size: 1.7rem; line-height: 1; }}
.wordmark {{ font-weight: 700; font-size: 1.25rem; letter-spacing: -.01em; }}

.sb-section {{
  margin: 1.2rem .35rem .35rem;
  color: var(--faint);
  font-size: .72rem;
  font-weight: 600;
  letter-spacing: .06em;
  text-transform: uppercase;
}}

.sb-recent {{
  padding: 7px 12px;
  margin: 1px .15rem;
  border-radius: 9px;
  color: var(--muted);
  font-size: .86rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  cursor: default;
}}
.sb-recent:hover {{ background: {"rgba(0,0,0,.04)" if safe_theme == "light" else "rgba(255,255,255,.05)"}; color: var(--text); }}

.sb-footer {{
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 1.4rem;
  padding: 10px 8px 0;
  border-top: 1px solid var(--border);
}}
.sb-user {{ display: flex; flex-direction: column; line-height: 1.25; }}
.sb-user strong {{ font-size: .9rem; }}
.sb-user small {{ color: var(--faint); font-size: .74rem; }}

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

/* New-conversation button (accent) + nav buttons (quiet list). */
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

[data-testid="stSidebar"] .stButton > button {{
  justify-content: flex-start;
  text-align: left;
  border: none;
  background: transparent;
  color: var(--muted);
  font-weight: 500;
  border-radius: 9px;
  padding: 8px 12px;
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

/* ---- Chat (native chat_message / chat_input) ---------------------------- */

.greeting {{
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 1rem 0 1.6rem;
  font-family: Georgia, "Times New Roman", serif;
  font-size: 1.8rem;
  letter-spacing: -.01em;
}}

[data-testid="stChatMessage"] {{
  background: transparent;
  padding: .35rem 0;
  gap: .7rem;
}}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {{
  background: var(--user-bubble);
  border-radius: 16px;
  padding: .4rem 1rem;
  margin: .5rem 0;
}}
[data-testid="stChatMessageAvatarAssistant"] {{
  background: var(--accent-soft) !important;
  color: var(--accent) !important;
  border: 1px solid var(--border);
}}
[data-testid="stChatMessageAvatarUser"] {{
  background: var(--surface-soft) !important;
  border: 1px solid var(--border);
}}

[data-testid="stChatInput"] {{
  background: var(--surface) !important;
  border: 1px solid var(--border-strong) !important;
  border-radius: 24px !important;
}}
[data-testid="stChatInput"]:focus-within {{ border-color: var(--accent) !important; }}
[data-testid="stChatInput"] textarea {{ color: var(--text) !important; }}
[data-testid="stChatInput"] textarea::placeholder {{ color: var(--faint) !important; }}
[data-testid="stChatInputSubmitButton"] {{ color: var(--accent) !important; }}
[data-testid="stBottom"] > div {{ background: var(--bg) !important; }}

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
.stToggle label, .stToggle p {{ color: var(--muted) !important; }}

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

.muted {{ margin: 0; color: var(--muted); font-size: .85rem; }}
</style>
"""
