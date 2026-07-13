import {
  Database,
  Radar,
  Sparkles,
  ShieldCheck,
  Sun,
  Moon,
  Layers,
  ArrowRight,
  RefreshCw,
  Play,
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { useApp } from '../context/AppContext';
import BrandMark from './BrandMark';

// 6 premium capabilities
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
    icon: <Sparkles size={24} />,
    title: 'Deep synthesis',
    desc: 'Builds reflections from related memories after enough supporting evidence has accumulated.',
  },
  {
    icon: <ShieldCheck size={24} />,
    title: 'Retrieval sufficiency',
    desc: 'Routes each query to quick, relational, or deep retrieval and preserves the evidence used in the answer.',
  },
];

// 4-step flow
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

// Eval dashboard categories
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
      {/* Glow overlays */}
      <div className="landing-glow glow-top-left" />
      <div className="landing-glow glow-bottom-right" />

      {/* Sticky Premium Navbar */}
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
        {/* Hero Section */}
        <section className="hero">
          <div className="hero-badge">
            <span className="badge-dot" />
            Memory-Integrated Reasoning Architecture
          </div>

          <h1 className="hero-title">
            Memory infrastructure<br />
            for <span className="highlight-text">long-running agents</span>.
          </h1>

          <p className="hero-sub">
            MIRA turns conversation history into structured, inspectable memory. It preserves corrections, retrieves across sessions, and shows the evidence behind each answer.
          </p>

          <div className="hero-ctas">
            <button className="btn-primary" onClick={handleLaunch}>
              Launch MIRA
              <ArrowRight size={16} />
            </button>
            <a
              className="btn-secondary"
              href="#results"
              onClick={(e) => scrollToSection('results', e)}
            >
              View Evaluation
            </a>
          </div>

          {/* Trust/Status pills */}
          <div className="hero-status-pills">
            <span className="status-pill"><span className="status-indicator pass" /> Local regression suite</span>
            <span className="status-pill"><span className="status-indicator active" /> Cross-session recall</span>
            <span className="status-pill"><span className="status-indicator active" /> Typed memory graph</span>
            <span className="status-pill"><span className="status-indicator active" /> Answer traces</span>
          </div>
        </section>

        {/* Hero Cockpit / Memory Engine Visual */}
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
                {/* SVG connection graph */}
                <svg className="cockpit-network-svg" viewBox="0 0 400 300">
                  <defs>
                    <linearGradient id="gradient-line" x1="0%" y1="0%" x2="100%" y2="100%">
                      <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.8" />
                      <stop offset="100%" stopColor="var(--accent-glow)" stopOpacity="0.2" />
                    </linearGradient>
                  </defs>

                  {/* Glowing Connection Lines */}
                  <g className="network-lines">
                    <line x1="200" y1="150" x2="100" y2="80" stroke="url(#gradient-line)" strokeWidth="1.5" strokeDasharray="4 2" />
                    <line x1="200" y1="150" x2="300" y2="80" stroke="url(#gradient-line)" strokeWidth="1.5" />
                    <line x1="200" y1="150" x2="110" y2="220" stroke="url(#gradient-line)" strokeWidth="1.5" />
                    <line x1="200" y1="150" x2="290" y2="220" stroke="url(#gradient-line)" strokeWidth="1.5" strokeDasharray="6 3" />
                    <line x1="100" y1="80" x2="300" y2="80" stroke="var(--border-strong)" strokeWidth="1" />
                    <line x1="110" y1="220" x2="290" y2="220" stroke="var(--border-strong)" strokeWidth="1" />
                  </g>

                  {/* Graph Nodes */}
                  <g className="network-nodes">
                    {/* Center Core */}
                    <circle cx="200" cy="150" r="28" fill="var(--surface-soft)" stroke="var(--accent)" strokeWidth="2.5" />
                    <circle cx="200" cy="150" r="4" fill="var(--accent)" />
                    <text x="200" y="154" textAnchor="middle" fill="var(--text)" fontSize="9" fontWeight="700">MIRA</text>

                    {/* Nodes around */}
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

        {/* Capabilities Section */}
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

        {/* How It Works Section */}
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

        {/* Evaluation Section */}
        <section id="results" className="section-padding">
          <div className="section-meta-eyebrow">Evaluation</div>
          <h2 className="section-h2">Inspect answers and the mechanism behind them</h2>
          <p className="section-subtitle-text">
            Local regression cases check recall, correction handling, routing, foresight, and graph evidence. Live benchmark results are reported separately.
          </p>

          {/* Validation Dashboard Interface */}
          <div className="validation-dashboard">
            <div className="validation-main-panel">
              <div className="dashboard-grid">
                {/* Score */}
                <div className="dashboard-metric-header">
                  <div className="dashboard-circular-progress">
                    <div className="progress-ring">
                      <strong>100%</strong>
                      <span>Pass Rate</span>
                    </div>
                  </div>
                  <div>
                    <h3 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 800 }}>Assertion Suite Health</h3>
                    <p style={{ margin: '4px 0 0', color: 'var(--muted)', fontSize: '0.82rem' }}>
                      Automated testing of memory consistency models.
                    </p>
                  </div>
                </div>

                {/* Score indicators */}
                <div className="dashboard-stats-strip">
                  <div className="stat-item">
                    <span className="stat-lbl">Passed</span>
                    <strong className="stat-val pass">10</strong>
                  </div>
                  <div className="stat-item">
                    <span className="stat-lbl">Failed</span>
                    <strong className="stat-val fail">0</strong>
                  </div>
                  <div className="stat-item">
                    <span className="stat-lbl">Pass Rate</span>
                    <strong className="stat-val pass">1.0</strong>
                  </div>
                  <div className="stat-item">
                    <span className="stat-lbl">Routers Active</span>
                    <strong className="stat-val neutral">Quick / Relational / Deep</strong>
                  </div>
                </div>
              </div>
            </div>

            {/* Category Checks */}
            <div className="dashboard-categories-container">
              <h4 className="categories-header-label">Verification Matrix (7 core conditions)</h4>
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

        {/* Final CTA */}
        <section className="final-cta-section">
          <div className="final-cta-glow" />
          <div className="final-cta-card">
            <h2>Inspect MIRA on a real conversation.</h2>
            <p>Open the demo to follow a message through persistence, retrieval, graph updates, and its final answer trace.</p>
            <button className="btn-primary" onClick={handleLaunch} style={{ margin: '0 auto' }}>
              Launch MIRA
              <ArrowRight size={16} />
            </button>
          </div>
        </section>

        {/* Footer */}
        <div className="landing-footer">
          MIRA · Memory-Integrated Reasoning Architecture · Built for durable reasoning
        </div>
      </div>
    </div>
  );
}
