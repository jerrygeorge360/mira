import {
  Database,
  Radar,
  Network,
  ShieldCheck,
  Sun,
  Moon,
  Layers,
  ArrowRight,
  RefreshCw,
  Play,
  Cable,
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { useApp } from '../context/AppContext';
import BrandMark from './BrandMark';

const CAPABILITIES = [
  {
    icon: <Database size={24} />,
    title: 'Cross-session memory',
    desc: 'Consolidates observations into durable facts that remain available after the conversation ends.',
  },
  {
    icon: <Layers size={24} />,
    title: 'Session correction handling',
    desc: 'Applies corrections to the active working set immediately, then carries them into durable memory.',
  },
  {
    icon: <RefreshCw size={24} />,
    title: 'Contradiction & supersession',
    desc: 'Links conflicting facts and marks outdated information as superseded without deleting its history.',
  },
  {
    icon: <Radar size={24} />,
    title: 'Foresight activation',
    desc: 'Records commitments and deadlines, then retrieves them when time and context make them relevant.',
  },
  {
    icon: <Network size={24} />,
    title: 'Deep synthesis',
    desc: 'Builds reflections from related memories after enough supporting evidence has accumulated.',
  },
  {
    icon: <ShieldCheck size={24} />,
    title: 'Retrieval sufficiency',
    desc: 'Routes each query to quick, relational, or deep retrieval and preserves the evidence used in the answer.',
  },
];

const STEPS = [
  {
    num: '01',
    title: 'Observe',
    desc: 'Persists each conversational turn with its session and source metadata.',
    badge: 'Raw input'
  },
  {
    num: '02',
    title: 'Structure',
    desc: 'Extracts facts, entities, constraints, and typed relationships.',
    badge: 'Slow consolidation'
  },
  {
    num: '03',
    title: 'Retrieve',
    desc: 'Selects quick, relational, or deep retrieval based on the question.',
    badge: 'Two-speed pipeline'
  },
  {
    num: '04',
    title: 'Reason',
    desc: 'Adds the selected evidence to the model prompt and records an answer trace.',
    badge: 'Answer trace'
  },
];

const MEMORY_LAYERS = [
  {
    level: 'Level 1',
    title: 'Session Working Set',
    data: '{ correction: "PostgreSQL replaces MongoDB", state: "active" }',
  },
  {
    level: 'Level 2',
    title: 'Hot Memory',
    data: '[ recent_turns, active_constraints, current_goal ]',
  },
  {
    level: 'Level 3',
    title: 'Warm / Foresight Memory',
    data: '{ commitments: 1, next_trigger: "project migration" }',
  },
  {
    level: 'Level 4',
    title: 'Durable Graph',
    data: '{ fact: "database = PostgreSQL", edge: "SUPERSEDES" }',
  },
];

const PIPELINE_STAGES = [
  {
    name: 'Observe',
    layer: 0,
    event: 'Turn persisted',
    detail: 'The correction enters the session working set immediately.',
  },
  {
    name: 'Promote',
    layer: 1,
    event: 'Hot memory updated',
    detail: 'The confirmed correction becomes available across sessions.',
  },
  {
    name: 'Consolidate',
    layer: 3,
    event: 'Fact structured',
    detail: 'The slow path extracts the updated fact and links its evidence.',
  },
  {
    name: 'Recall',
    layer: 1,
    event: 'Evidence retrieved',
    detail: 'A later session retrieves the active fact from hot memory.',
  },
  {
    name: 'Foresight',
    layer: 2,
    event: 'Trigger checked',
    detail: 'Time-sensitive memory is included only when the query makes it relevant.',
  },
  {
    name: 'Supersede',
    layer: 0,
    event: 'Old fact retired',
    detail: 'The previous database fact remains traceable but is no longer active.',
  },
];

const HERO_LEDGER = [
  {
    label: 'Fast path',
    value: 'Turn persisted',
    detail: 'Conversation saved with session, workspace, and source metadata.',
    status: '142 ms',
  },
  {
    label: 'Working set',
    value: 'Correction active',
    detail: '“PostgreSQL replaces MongoDB” is used before durable consolidation finishes.',
    status: 'hot',
  },
  {
    label: 'Graph edge',
    value: 'SUPERSEDED_BY',
    detail: 'Old database memory remains traceable but is no longer active.',
    status: 'typed',
  },
  {
    label: 'Answer trace',
    value: '4 evidence sources',
    detail: 'The response keeps the memories, route, and sufficiency check inspectable.',
    status: 'audit',
  },
  {
    label: 'Context budget',
    value: 'Compact evidence',
    detail: 'The prompt builder uses selected memory instead of replaying the full transcript.',
    status: 'trimmed',
  },
];

const TRACK_PROOF = [
  {
    title: 'Accumulates experience',
    claim: 'Preferences, corrections, decisions, commitments, and facts are persisted with workspace and source metadata.',
    backing: 'Fast observation storage + session working set + slow-path durable extraction.',
  },
  {
    title: 'Keeps user preferences active',
    claim: 'Session corrections and durable preferences can influence later answers without asking the user to repeat them.',
    backing: 'Session working set, hot memory, active constraints, and prompt context merging.',
  },
  {
    title: 'Retires outdated memory',
    claim: 'Old values are not blindly deleted; they become inactive when newer evidence supersedes them.',
    backing: 'CONTRADICTS / SUPERSEDED_BY graph edges, validity windows, and hot-memory demotion triggers.',
  },
  {
    title: 'Retrieves under a context budget',
    claim: 'MIRA routes to quick, relational, or deep retrieval and trims lower-priority context before the answer prompt.',
    backing: 'Retrieval router, Chroma-backed vector search, graph traversal, and prompt budget allocation.',
  },
];

const USER_FLOW = [
  {
    title: 'Say what matters once',
    text: 'Tell the assistant your preference, decision, project detail, or deadline.',
  },
  {
    title: 'Correct it when plans change',
    text: 'MIRA keeps the new value active and marks the old one as superseded.',
  },
  {
    title: 'Return in a later session',
    text: 'The agent retrieves the useful memory without replaying the whole chat.',
  },
  {
    title: 'Check why it answered',
    text: 'Open the trace to see the memory records and relationships behind the response.',
  },
];

const EVAL_CATEGORIES = [
  { name: 'Direct fact recall', checks: 'Retrieval matching specific attributes directly from past turns.', status: 'PASSED' },
  { name: 'Cross-session recall', checks: 'Recall of verified facts across session boundaries.', status: 'PASSED' },
  { name: 'Contradiction handling', checks: 'Detection of new data conflicting with existing database records.', status: 'PASSED' },
  { name: 'Supersession', checks: 'Replacing outdated nodes in the temporal graph with newer observations.', status: 'PASSED' },
  { name: 'Foresight', checks: 'Actionable intent registration and timely warning/trigger matching.', status: 'PASSED' },
  { name: 'Deep synthesis', checks: 'Leiden cluster reflections and higher-order summary extraction.', status: 'PASSED' },
  { name: 'Routing intent', checks: 'Accurately selecting between direct, quick, relational, or deep retrieval.', status: 'PASSED' },
];

export default function Landing() {
  const { setPage, theme, toggleTheme } = useApp();
  const [pipelineStage, setPipelineStage] = useState(0);
  const [pipelineRunning, setPipelineRunning] = useState(false);

  useEffect(() => {
    if (!pipelineRunning) return;
    const timer = window.setTimeout(() => {
      if (pipelineStage === PIPELINE_STAGES.length - 1) {
        setPipelineRunning(false);
        return;
      }
      setPipelineStage((stage) => stage + 1);
    }, 1400);
    return () => window.clearTimeout(timer);
  }, [pipelineRunning, pipelineStage]);

  const activePipelineStage = PIPELINE_STAGES[pipelineStage];

  const runPipeline = () => {
    setPipelineStage(0);
    setPipelineRunning(true);
  };

  const handleLaunch = () => {
    setPage('auth');
  };

  const scrollToSection = (id: string, e: React.MouseEvent) => {
    e.preventDefault();
    const el = document.getElementById(id);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth' });
    }
  };

  return (
    <div className="landing">
      <nav className="landing-nav">
        <div className="landing-brand">
          <BrandMark className="brand-mark" size={25} />
          <span>MIRA</span>
        </div>
        <div className="landing-nav-links">
          <a href="#capabilities" onClick={(e) => scrollToSection('capabilities', e)}>Capabilities</a>
          <a href="#how-it-works" onClick={(e) => scrollToSection('how-it-works', e)}>How it works</a>
          <a href="#results" onClick={(e) => scrollToSection('results', e)}>Evaluation</a>
        </div>
        <div className="landing-nav-actions">
          <button className="theme-toggle" onClick={toggleTheme} title="Toggle theme">
            {theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
          </button>
          <button className="btn-navbar" onClick={handleLaunch}>
            Launch App
            <ArrowRight size={14} />
          </button>
        </div>
      </nav>

      <div className="landing-content">
        <section className="hero">
          <div className="hero-copy">
            <div className="hero-badge">
              <span className="badge-dot" />
              Persistent memory for AI assistants
            </div>

            <h1 className="hero-title">
              Your AI assistant should remember what matters.
            </h1>

            <p className="hero-sub">
              MIRA helps agents carry preferences, decisions, corrections, and commitments
              across sessions. When something changes, old memories are retired instead of
              silently reused. When the agent answers, you can inspect which memories shaped it.
            </p>

            <div className="hero-ctas">
              <button className="btn-primary" onClick={handleLaunch}>
                Launch MIRA
                <ArrowRight size={16} />
              </button>
              <a
                className="btn-secondary"
                href="#how-it-works"
                onClick={(e) => scrollToSection('how-it-works', e)}
              >
                See how memory works
              </a>
            </div>

            <div className="hero-status-pills">
              <span className="status-pill"><span className="status-indicator pass" /> Remembers preferences</span>
              <span className="status-pill"><span className="status-indicator active" /> Handles corrections</span>
              <span className="status-pill"><span className="status-indicator active" /> Explains evidence</span>
              <span className="status-pill"><span className="status-indicator active" /> Works across sessions</span>
            </div>
          </div>

          <aside className="hero-ledger" aria-label="MIRA memory runtime ledger">
            <div className="hero-ledger-top">
              <span>Runtime ledger</span>
              <strong>demo workspace</strong>
            </div>
            <div className="hero-ledger-query">
              <span>Later, the user asks</span>
              <p>“Which database are we using now?”</p>
            </div>
            <div className="hero-ledger-rows">
              {HERO_LEDGER.map((row) => (
                <div className="hero-ledger-row" key={row.label}>
                  <div>
                    <span>{row.label}</span>
                    <strong>{row.value}</strong>
                    <p>{row.detail}</p>
                  </div>
                  <code>{row.status}</code>
                </div>
              ))}
            </div>
            <div className="hero-ledger-answer">
              <span>MIRA answers with</span>
              <strong>PostgreSQL</strong>
              <p>because the newer correction superseded the older MongoDB memory.</p>
            </div>
          </aside>
        </section>

        <section className="consumer-flow-section">
          <div className="consumer-flow-header">
            <span>What this feels like</span>
            <h2>A memory layer you can inspect, not just trust.</h2>
          </div>
          <div className="consumer-flow-grid">
            {USER_FLOW.map((item, index) => (
              <article className="consumer-flow-card" key={item.title}>
                <span>{String(index + 1).padStart(2, '0')}</span>
                <h3>{item.title}</h3>
                <p>{item.text}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="visual-section">
          <div className="visual-header-cap">Memory pipeline · Runtime view</div>

          <div className="engine-cockpit">
            {/* Left: Memory Layers */}
            <div className="cockpit-layers">
              <div className="cockpit-heading-row">
                <h4>Memory layers</h4>
                <button className="pipeline-run" onClick={runPipeline} disabled={pipelineRunning}>
                  <Play size={13} fill="currentColor" />
                  {pipelineRunning ? 'Running' : 'Run sequence'}
                </button>
              </div>

              {MEMORY_LAYERS.map((layer, index) => {
                const active = activePipelineStage.layer === index;
                return (
                  <button
                    className={`cockpit-layer${active ? ' layer-active' : ''}`}
                    key={layer.level}
                    onClick={() => {
                      const matchingStage = PIPELINE_STAGES.findIndex((stage) => stage.layer === index);
                      if (matchingStage >= 0) setPipelineStage(matchingStage);
                      setPipelineRunning(false);
                    }}
                    type="button"
                  >
                    <div className="layer-header">
                      <span className={`layer-tag${active ? ' active' : ''}`}>{layer.level}</span>
                      <h5>{layer.title}</h5>
                    </div>
                    <div className="layer-data font-mono">{layer.data}</div>
                  </button>
                );
              })}
            </div>

            {/* Right: Network Graph & Floating Actions */}
            <div className="cockpit-visualization">
              <div className="visualization-display">
                <svg className="cockpit-network-svg" viewBox="0 0 400 300">
                  <defs>
                    <linearGradient id="gradient-line" x1="0%" y1="0%" x2="100%" y2="100%">
                      <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.8" />
                      <stop offset="100%" stopColor="var(--accent-glow)" stopOpacity="0.2" />
                    </linearGradient>
                  </defs>

                  <g className="network-lines">
                    <line x1="200" y1="150" x2="100" y2="80" stroke="url(#gradient-line)" strokeWidth="1.5" strokeDasharray="4 2" />
                    <line x1="200" y1="150" x2="300" y2="80" stroke="url(#gradient-line)" strokeWidth="1.5" />
                    <line x1="200" y1="150" x2="110" y2="220" stroke="url(#gradient-line)" strokeWidth="1.5" />
                    <line x1="200" y1="150" x2="290" y2="220" stroke="url(#gradient-line)" strokeWidth="1.5" strokeDasharray="6 3" />
                    <line x1="100" y1="80" x2="300" y2="80" stroke="var(--border-strong)" strokeWidth="1" />
                    <line x1="110" y1="220" x2="290" y2="220" stroke="var(--border-strong)" strokeWidth="1" />
                  </g>

                  <g className="network-nodes">
                    <circle cx="200" cy="150" r="28" fill="var(--surface-soft)" stroke="var(--accent)" strokeWidth="2.5" />
                    <circle cx="200" cy="150" r="4" fill="var(--accent)" />
                    <text x="200" y="154" textAnchor="middle" fill="var(--text)" fontSize="9" fontWeight="700">MIRA</text>

                    <g className={`nodes-group${activePipelineStage.layer === 0 || activePipelineStage.layer === 1 ? ' node-active' : ''}`}>
                      <circle cx="100" cy="80" r="16" fill="var(--surface)" stroke="var(--border-strong)" strokeWidth="1.5" />
                      <text x="100" y="83" textAnchor="middle" fill="var(--muted)" fontSize="8">Facts</text>
                      <circle cx="100" cy="80" r="3" fill="#3fb27f" />
                    </g>

                    <g className={`nodes-group${activePipelineStage.layer === 3 ? ' node-active' : ''}`}>
                      <circle cx="300" cy="80" r="16" fill="var(--surface)" stroke="var(--border-strong)" strokeWidth="1.5" />
                      <text x="300" y="83" textAnchor="middle" fill="var(--muted)" fontSize="8">Graph</text>
                      <circle cx="300" cy="80" r="3" fill="#e0a13a" />
                    </g>

                    <g className={`nodes-group${activePipelineStage.layer === 2 ? ' node-active' : ''}`}>
                      <circle cx="110" cy="220" r="16" fill="var(--surface)" stroke="var(--border-strong)" strokeWidth="1.5" />
                      <text x="110" y="223" textAnchor="middle" fill="var(--muted)" fontSize="8">Future</text>
                      <circle cx="110" cy="220" r="3" fill="var(--accent)" />
                    </g>

                    <g className={`nodes-group${activePipelineStage.layer === 3 ? ' node-active' : ''}`}>
                      <circle cx="290" cy="220" r="16" fill="var(--surface)" stroke="var(--border-strong)" strokeWidth="1.5" />
                      <text x="290" y="223" textAnchor="middle" fill="var(--muted)" fontSize="8">Reflect</text>
                      <circle cx="290" cy="220" r="3" fill="#9b7ad6" />
                    </g>
                  </g>
                </svg>

                <div className="pipeline-event" aria-live="polite">
                  <span>{activePipelineStage.name}</span>
                  <strong>{activePipelineStage.event}</strong>
                  <p>{activePipelineStage.detail}</p>
                </div>
              </div>
              <div className="pipeline-stage-tabs" aria-label="Memory pipeline stages">
                {PIPELINE_STAGES.map((stage, index) => (
                  <button
                    className={pipelineStage === index ? 'active' : ''}
                    key={stage.name}
                    onClick={() => {
                      setPipelineStage(index);
                      setPipelineRunning(false);
                    }}
                    type="button"
                  >
                    <span>{index + 1}</span>
                    {stage.name}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section id="capabilities" className="section-padding">
          <div className="section-meta-eyebrow">Core memory components</div>
          <h2 className="section-h2">A working memory loop, not a longer prompt</h2>
          <p className="section-subtitle-text">
            Each component has a defined role in persistence, consolidation, retrieval, or inspection.
          </p>

          <div className="features-grid">
            {CAPABILITIES.map((f, i) => (
              <div key={i} className="feature-card">
                <div className="feature-icon-wrapper">{f.icon}</div>
                <h3>{f.title}</h3>
                <p>{f.desc}</p>
              </div>
            ))}
          </div>
        </section>

        <section id="mcp" className="mcp-access-section" aria-labelledby="mcp-access-title">
          <div className="mcp-access-copy">
            <div className="mcp-access-eyebrow">
              <Cable size={15} />
              Agent integration
            </div>
            <h2 id="mcp-access-title">Use MIRA's memory tools from an MCP client.</h2>
            <p>
              MIRA exposes its active retrieval, graph, foresight, and session-memory operations
              through an authenticated MCP endpoint. OAuth binds each client to the user's
              workspace before any memory tool runs.
            </p>
          </div>
          <div className="mcp-access-details" aria-label="MCP service details">
            <div>
              <span>Transport</span>
              <strong>Streamable HTTP</strong>
            </div>
            <div>
              <span>Authorization</span>
              <strong>OAuth 2.1 + PKCE</strong>
            </div>
            <div>
              <span>Data boundary</span>
              <strong>Workspace-scoped</strong>
            </div>
            <code>https://mira.ninja/mcp</code>
          </div>
        </section>

        <section className="section-padding track-proof-section">
          <div className="section-meta-eyebrow">MemoryAgent fit</div>
          <h2 className="section-h2">Track claims, backed by runtime pieces</h2>
          <p className="section-subtitle-text">
            These are not brochure claims. Each behavior maps to a concrete part of MIRA’s current architecture.
          </p>

          <div className="track-proof-grid">
            {TRACK_PROOF.map((item) => (
              <article className="track-proof-card" key={item.title}>
                <h3>{item.title}</h3>
                <p>{item.claim}</p>
                <div>
                  <span>Backed by</span>
                  <strong>{item.backing}</strong>
                </div>
              </article>
            ))}
          </div>
        </section>

        <section id="how-it-works" className="section-padding">
          <div className="section-meta-eyebrow">Memory lifecycle</div>
          <h2 className="section-h2">From conversation to evidence</h2>
          <p className="section-subtitle-text">
            The fast path preserves the turn immediately. Background processing structures durable memory for later retrieval.
          </p>

          <div className="how-it-works-pipeline">
            {STEPS.map((s, i) => (
              <div key={i} className="pipeline-step">
                <div className="pipeline-step-top">
                  <div className="pipeline-number">{s.num}</div>
                  <span className="pipeline-badge">{s.badge}</span>
                </div>
                <h3>{s.title}</h3>
                <p>{s.desc}</p>
                {i < STEPS.length - 1 && (
                  <div className="pipeline-connector-line">
                    <ArrowRight size={20} className="connector-arrow" />
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>

        <section id="results" className="section-padding">
          <div className="section-meta-eyebrow">Evaluation</div>
          <h2 className="section-h2">Inspect answers and the mechanism behind them</h2>
          <p className="section-subtitle-text">
            Local regression cases check recall, correction handling, routing, foresight, and graph evidence. Live benchmark results are reported separately.
          </p>

          <div className="validation-dashboard">
            <div className="validation-main-panel">
              <div className="dashboard-grid">
                <div className="dashboard-metric-header">
                  <div className="dashboard-circular-progress">
                    <div className="progress-ring">
                      <strong>100%</strong>
                      <span>Pass Rate</span>
                    </div>
                  </div>
                  <div>
                    <h3 className="dashboard-title">Local Evaluation Health</h3>
                    <p className="dashboard-caption">
                      Saved local cases check answers, retrieval mode, trace evidence, and graph behavior.
                    </p>
                  </div>
                </div>

                <div className="dashboard-stats-strip">
                  <div className="stat-item">
                    <span className="stat-lbl">Passed</span>
                    <strong className="stat-val pass">13</strong>
                  </div>
                  <div className="stat-item">
                    <span className="stat-lbl">Failed</span>
                    <strong className="stat-val fail">0</strong>
                  </div>
                  <div className="stat-item">
                    <span className="stat-lbl">Pass Rate</span>
                    <strong className="stat-val pass">100%</strong>
                  </div>
                  <div className="stat-item">
                    <span className="stat-lbl">Routers Active</span>
                    <strong className="stat-val neutral">Quick / Relational / Deep</strong>
                  </div>
                </div>
              </div>
            </div>

            <div className="dashboard-categories-container">
              <h4 className="categories-header-label">Verification matrix · 7 behavior groups</h4>
              <div className="category-grid">
                {EVAL_CATEGORIES.map((c, i) => (
                  <div key={i} className="dashboard-category-card">
                    <div className="category-top">
                      <span className="category-name">{c.name}</span>
                      <span className="category-status badge-pass">PASSED</span>
                    </div>
                    <p className="category-details">{c.checks}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className="final-cta-section">
          <div className="final-cta-card">
            <h2>Inspect the memory loop on a real conversation.</h2>
            <p>Open the demo to follow a message through persistence, retrieval, graph updates, and its final answer trace.</p>
            <button className="btn-primary centered-cta" onClick={handleLaunch}>
              Launch MIRA
              <ArrowRight size={16} />
            </button>
          </div>
        </section>

        <footer className="landing-footer">
          <div className="landing-footer-brand">
            <div className="landing-brand">
              <BrandMark className="brand-mark" size={22} />
              <span>MIRA</span>
            </div>
            <p>
              Memory infrastructure for agents that need durable context, correction handling,
              retrieval traces, and inspectable graph-backed memory.
            </p>
          </div>

          <nav className="landing-footer-links" aria-label="Footer navigation">
            <div>
              <span>Product</span>
              <a href="#capabilities" onClick={(e) => scrollToSection('capabilities', e)}>Capabilities</a>
              <a href="#how-it-works" onClick={(e) => scrollToSection('how-it-works', e)}>Memory lifecycle</a>
              <a href="#results" onClick={(e) => scrollToSection('results', e)}>Evaluation</a>
              <a href="/sitemap.xml">Sitemap</a>
            </div>
            <div>
              <span>Runtime</span>
              <button type="button" onClick={handleLaunch}>Open workspace</button>
              <button type="button" onClick={runPipeline}>Run pipeline view</button>
              <a href="#mcp" onClick={(e) => scrollToSection('mcp', e)}>MCP access</a>
              <span className="footer-note">SQLite truth · Chroma index · typed graph</span>
            </div>
            <div>
              <span>Contact</span>
              <a href="https://github.com/jerrygeorge360" target="_blank" rel="noreferrer">
                GitHub · jerrygeorge360
              </a>
            </div>
          </nav>
        </footer>
      </div>
    </div>
  );
}
