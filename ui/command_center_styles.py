# ruff: noqa: E501
"""Custom CSS for the MIRA Memory Command Center.

Ownership: Sarah.
Related issue: ISSUE-130.
Architecture area: UI.
"""

from __future__ import annotations


def command_center_css(theme: str) -> str:
    """Return the custom CSS layer for the selected theme."""
    safe_theme = "light" if theme == "light" else "dark"
    return f"""
<style>
:root {{
  --radius-xl: 28px;
  --radius-lg: 22px;
  --radius-md: 16px;
  --radius-sm: 12px;
  --ease: cubic-bezier(.2,.8,.2,1);
}}

.mira-shell[data-theme="{safe_theme}"] {{
  --bg: {'#eef3fb' if safe_theme == 'light' else '#050812'};
  --bg-2: {'#f8fbff' if safe_theme == 'light' else '#09111f'};
  --panel: {'rgba(255,255,255,.78)' if safe_theme == 'light' else 'rgba(13, 22, 38, .78)'};
  --panel-strong: {'rgba(255,255,255,.94)' if safe_theme == 'light' else 'rgba(18, 30, 52, .94)'};
  --panel-soft: {'rgba(239,246,255,.84)' if safe_theme == 'light' else 'rgba(10, 18, 32, .62)'};
  --text: {'#111827' if safe_theme == 'light' else '#ecf7ff'};
  --muted: {'#5e6b82' if safe_theme == 'light' else '#8fa3bf'};
  --faint: {'#8290a8' if safe_theme == 'light' else '#61748f'};
  --border: {'rgba(98, 119, 154, .20)' if safe_theme == 'light' else 'rgba(139, 226, 255, .14)'};
  --border-strong: {'rgba(60, 95, 190, .24)' if safe_theme == 'light' else 'rgba(101, 229, 255, .28)'};
  --shadow: {'0 22px 70px rgba(46, 76, 140, .18)' if safe_theme == 'light' else '0 22px 90px rgba(0, 0, 0, .42)'};
  --glow: {'0 0 36px rgba(92, 116, 255, .18)' if safe_theme == 'light' else '0 0 44px rgba(39, 226, 255, .18)'};
  --accent: #23d5ff;
  --accent-2: #8b5cf6;
  --accent-3: #21e6a8;
  --warning: #fbbf24;
  --danger: #fb7185;
  --success: #22c55e;
  color: var(--text);
}}

html, body, [data-testid="stAppViewContainer"] {{
  background:
    radial-gradient(circle at top left, {'rgba(82, 111, 255, .18)' if safe_theme == 'light' else 'rgba(16, 185, 255, .16)'}, transparent 32rem),
    radial-gradient(circle at 82% 8%, {'rgba(139, 92, 246, .14)' if safe_theme == 'light' else 'rgba(139, 92, 246, .16)'}, transparent 28rem),
    linear-gradient(135deg, var(--bg), var(--bg-2)) !important;
}}

[data-testid="stHeader"], [data-testid="stToolbar"], footer {{
  display: none !important;
}}

.block-container {{
  max-width: 100% !important;
  padding: 1.2rem 1.4rem 1.6rem !important;
}}

.mira-shell * {{
  box-sizing: border-box;
}}

.mira-shell {{
  position: relative;
  min-height: 100vh;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}}

.mira-grid {{
  display: grid;
  grid-template-columns: 280px minmax(420px, 1.25fr) minmax(330px, .85fr);
  grid-template-rows: auto minmax(640px, auto) auto;
  gap: 18px;
  align-items: stretch;
}}

.glass {{
  background:
    linear-gradient(145deg, rgba(255,255,255,.09), rgba(255,255,255,.02)),
    var(--panel);
  border: 1px solid var(--border);
  box-shadow: var(--shadow);
  backdrop-filter: blur(22px);
  -webkit-backdrop-filter: blur(22px);
}}

.sidebar {{
  grid-row: 1 / span 3;
  min-height: calc(100vh - 2.8rem);
  border-radius: var(--radius-xl);
  padding: 22px;
  position: sticky;
  top: 1.2rem;
  overflow: hidden;
}}

.sidebar::before, .command-card::before, .memory-graph::before {{
  content: "";
  position: absolute;
  inset: -2px;
  pointer-events: none;
  background: radial-gradient(circle at 20% 0%, rgba(35, 213, 255, .22), transparent 28rem);
  opacity: .75;
}}

.brand {{
  position: relative;
  display: flex;
  gap: 13px;
  align-items: center;
  margin-bottom: 28px;
}}

.logo-mark {{
  width: 48px;
  height: 48px;
  border-radius: 17px;
  display: grid;
  place-items: center;
  font-weight: 900;
  letter-spacing: -.08em;
  color: #04111f;
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  box-shadow: 0 0 30px rgba(35, 213, 255, .34);
}}

.brand h1, .panel-title h3, .chat-title h2 {{
  margin: 0;
  letter-spacing: -.04em;
}}

.brand h1 {{
  font-size: 1.55rem;
}}

.brand p, .muted {{
  margin: 0;
  color: var(--muted);
  font-size: .82rem;
}}

.nav-stack {{
  position: relative;
  display: grid;
  gap: 8px;
}}

.nav-item {{
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 16px;
  color: var(--muted);
  border: 1px solid transparent;
  transition: transform .2s var(--ease), border .2s var(--ease), background .2s var(--ease);
}}

.nav-item.active, .nav-item:hover {{
  color: var(--text);
  transform: translateX(2px);
  border-color: var(--border-strong);
  background: linear-gradient(135deg, rgba(35, 213, 255, .13), rgba(139, 92, 246, .12));
}}

.nav-icon {{
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border-radius: 11px;
  background: var(--panel-soft);
  color: var(--accent);
}}

.sidebar-bottom {{
  position: absolute;
  left: 22px;
  right: 22px;
  bottom: 22px;
  display: grid;
  gap: 12px;
}}

.status-card {{
  border-radius: 20px;
  padding: 15px;
  background: var(--panel-soft);
  border: 1px solid var(--border);
}}

.status-online {{
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: .75rem;
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

.primary-btn {{
  display: flex;
  justify-content: center;
  align-items: center;
  border-radius: 16px;
  padding: 13px 16px;
  color: #04111f;
  font-weight: 850;
  background: linear-gradient(135deg, var(--accent), var(--accent-3));
  box-shadow: 0 16px 38px rgba(35, 213, 255, .25);
}}

.topbar {{
  grid-column: 2 / span 2;
  border-radius: var(--radius-xl);
  padding: 16px 18px;
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
}}

.toolbar-left, .toolbar-right, .profile-chip, .model-chip {{
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}}

.chip, .model-chip, .search-box, .profile-chip, .icon-btn, .badge {{
  border: 1px solid var(--border);
  background: var(--panel-soft);
  border-radius: 999px;
}}

.model-chip, .search-box, .profile-chip {{
  padding: 10px 13px;
}}

.model-chip {{
  color: var(--accent);
  font-weight: 850;
  letter-spacing: .04em;
}}

.search-box {{
  min-width: 250px;
  color: var(--muted);
}}

.icon-btn {{
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
}}

.avatar {{
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  color: white;
  background: linear-gradient(135deg, var(--accent-2), var(--accent));
  font-size: .78rem;
  font-weight: 900;
}}

.command-card {{
  position: relative;
  overflow: hidden;
  border-radius: var(--radius-xl);
  padding: 22px;
}}

.chat-panel {{
  grid-column: 2;
  min-height: 660px;
}}

.chat-title {{
  position: relative;
  display: flex;
  justify-content: space-between;
  align-items: start;
  margin-bottom: 18px;
}}

.chat-title h2 {{
  font-size: 2rem;
}}

.badge {{
  color: var(--accent);
  font-size: .72rem;
  font-weight: 850;
  padding: 5px 9px;
  letter-spacing: .08em;
}}

.chat-stream {{
  position: relative;
  display: grid;
  gap: 14px;
}}

.bubble {{
  border-radius: 22px;
  padding: 14px 16px;
  max-width: 82%;
  line-height: 1.55;
  border: 1px solid var(--border);
}}

.bubble.user {{
  margin-left: auto;
  background: linear-gradient(135deg, rgba(35, 213, 255, .18), rgba(139, 92, 246, .18));
}}

.bubble.assistant {{
  background: var(--panel-soft);
}}

.brief-card {{
  margin: 14px 0 8px;
  border-radius: 24px;
  padding: 18px;
  background: linear-gradient(135deg, rgba(35, 213, 255, .10), rgba(139, 92, 246, .08));
  border: 1px solid var(--border-strong);
}}

.brief-grid, .metric-grid {{
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}}

.brief-item, .metric-tile {{
  padding: 12px;
  border-radius: 16px;
  background: rgba(255,255,255,.045);
  border: 1px solid var(--border);
}}

.brief-item small, .metric-tile small {{
  display: block;
  color: var(--faint);
  margin-bottom: 4px;
}}

.brief-item strong, .metric-tile strong {{
  font-size: .92rem;
}}

.chip-row {{
  display: flex;
  flex-wrap: wrap;
  gap: 9px;
  margin-top: 14px;
}}

.chip {{
  display: inline-flex;
  color: var(--muted);
  padding: 8px 11px;
  font-size: .8rem;
}}

.composer {{
  margin-top: 18px;
  border-radius: 22px;
  padding: 12px;
  display: flex;
  gap: 10px;
  align-items: center;
  background: var(--panel-soft);
  border: 1px solid var(--border-strong);
}}

.composer-input {{
  flex: 1;
  color: var(--muted);
}}

.send-btn {{
  width: 44px;
  height: 44px;
  display: grid;
  place-items: center;
  border-radius: 15px;
  color: #04111f;
  background: linear-gradient(135deg, var(--accent), var(--accent-3));
  font-weight: 900;
}}

.right-stack {{
  grid-column: 3;
  display: grid;
  gap: 18px;
}}

.panel-title {{
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: start;
  margin-bottom: 14px;
}}

.panel-title h3 {{
  font-size: 1.04rem;
}}

.memory-graph {{
  position: relative;
  overflow: hidden;
}}

.graph-stage {{
  height: 220px;
  position: relative;
  border-radius: 22px;
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
}}

.node.main {{ width: 82px; height: 82px; left: calc(50% - 41px); top: 66px; }}
.node.n1 {{ width: 52px; height: 52px; left: 28px; top: 34px; color: var(--accent); }}
.node.n2 {{ width: 48px; height: 48px; right: 34px; top: 36px; color: var(--accent-2); }}
.node.n3 {{ width: 46px; height: 46px; left: 58px; bottom: 30px; color: var(--accent-3); }}
.node.n4 {{ width: 56px; height: 56px; right: 50px; bottom: 22px; color: var(--warning); }}

.edge {{
  position: absolute;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--accent), transparent);
  opacity: .55;
  transform-origin: left center;
}}
.edge.e1 {{ width: 145px; left: 76px; top: 76px; transform: rotate(22deg); }}
.edge.e2 {{ width: 132px; right: 78px; top: 82px; transform: rotate(-20deg); }}
.edge.e3 {{ width: 120px; left: 94px; bottom: 72px; transform: rotate(-18deg); }}
.edge.e4 {{ width: 122px; right: 96px; bottom: 72px; transform: rotate(19deg); }}

.list-stack {{
  display: grid;
  gap: 10px;
}}

.memory-row, .evidence-row, .reflection-card, .community-row, .timeline-card {{
  border-radius: 17px;
  padding: 12px;
  background: var(--panel-soft);
  border: 1px solid var(--border);
}}

.row-top {{
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
}}

.priority-high {{ color: var(--danger); }}
.priority-medium {{ color: var(--warning); }}
.priority-low {{ color: var(--accent-3); }}

.progress-track {{
  height: 9px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(127, 145, 172, .18);
  margin: 12px 0 14px;
}}

.progress-bar {{
  height: 100%;
  width: 72%;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--accent), var(--accent-2));
  box-shadow: 0 0 20px rgba(35, 213, 255, .26);
}}

.timeline {{
  grid-column: 2 / span 2;
  border-radius: var(--radius-xl);
  padding: 18px;
}}

.timeline-tabs {{
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
}}

.timeline-strip {{
  display: grid;
  grid-template-columns: repeat(6, minmax(160px, 1fr));
  gap: 12px;
  overflow-x: auto;
  padding-bottom: 4px;
}}

.timeline-card {{
  min-height: 112px;
  position: relative;
}}

.timeline-card::before {{
  content: "";
  position: absolute;
  left: 14px;
  top: 14px;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 18px var(--accent);
}}

.timeline-card .timeline-body {{
  padding-left: 20px;
}}

@media (max-width: 1180px) {{
  .mira-grid {{
    grid-template-columns: 250px 1fr;
  }}
  .topbar, .timeline {{
    grid-column: 2;
  }}
  .right-stack {{
    grid-column: 2;
  }}
}}

@media (max-width: 820px) {{
  .mira-grid {{
    display: block;
  }}
  .sidebar {{
    position: relative;
    top: 0;
    min-height: auto;
    margin-bottom: 16px;
  }}
  .sidebar-bottom {{
    position: relative;
    left: auto;
    right: auto;
    bottom: auto;
    margin-top: 20px;
  }}
  .topbar, .chat-panel, .right-stack, .timeline {{
    margin-bottom: 16px;
  }}
  .search-box {{
    min-width: 100%;
  }}
  .brief-grid, .metric-grid {{
    grid-template-columns: 1fr;
  }}
  .timeline-strip {{
    grid-template-columns: repeat(6, 220px);
  }}
}}
</style>
"""
