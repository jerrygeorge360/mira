import { ArrowRight, Moon, Play, RotateCcw, Sun } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useApp } from '../context/AppContext';
import BrandMark from './BrandMark';
import MemoryLayerGraph from './MemoryLayerGraph';
import { Num } from './view';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';

/* ─────────────────────────────────────────────────────────
 * LANDING — "Instrument"
 *
 * Type-led and left-aligned: every section is a labelled row
 * (index + name in the margin, content beside it) separated by
 * hairlines. Controls and tables are shadcn/ui components
 * (Button, ToggleGroup, Table, Badge, Separator); page layout
 * and type live in landing.css.
 *
 * Motion: the hero staggers in once on load, and the memory
 * pipeline figure plays its sequence the first time it scrolls
 * into view. Both are first-time, explanatory moments; the rest
 * of the page only changes colour.
 * ───────────────────────────────────────────────────────── */

/** An example trace for one question. Illustrative, and labelled as such on the page. */
const TRACE_ROWS = [
  { label: 'fast path', value: 'Turn saved', detail: 'Stored with its session, workspace and source.', status: '142 ms' },
  { label: 'working set', value: 'Correction active', detail: '“PostgreSQL replaces MongoDB” applies before consolidation finishes.', status: 'hot' },
  { label: 'graph edge', value: 'SUPERSEDED_BY', detail: 'The MongoDB fact stays traceable but is no longer active.', status: 'typed' },
  { label: 'answer trace', value: '4 evidence sources', detail: 'Memories, route and sufficiency check are kept with the answer.', status: 'audit' },
  { label: 'context budget', value: 'Selected evidence only', detail: 'The prompt carries chosen memory, not the whole transcript.', status: 'trimmed' },
];

const MEMORY_LAYERS = [
  { level: 'L1', title: 'Session working set', data: '{ correction: "PostgreSQL replaces MongoDB", state: "active" }' },
  { level: 'L2', title: 'Hot memory', data: '[ recent_turns, active_constraints, current_goal ]' },
  { level: 'L3', title: 'Warm / foresight', data: '{ commitments: 1, next_trigger: "project migration" }' },
  { level: 'L4', title: 'Durable graph', data: '{ fact: "database = PostgreSQL", edge: "SUPERSEDES" }' },
];

/** `flow` is the direction data moves: written into a layer, or read back out of it. */
const PIPELINE_STAGES: { name: string; layer: number; flow: 'write' | 'read'; event: string; detail: string }[] = [
  { name: 'Observe', layer: 0, flow: 'write', event: 'Turn saved', detail: 'The correction enters the session working set immediately.' },
  { name: 'Promote', layer: 1, flow: 'write', event: 'Hot memory updated', detail: 'The confirmed correction becomes available across sessions.' },
  { name: 'Consolidate', layer: 3, flow: 'write', event: 'Fact structured', detail: 'The slow path extracts the updated fact and links its evidence.' },
  { name: 'Recall', layer: 1, flow: 'read', event: 'Evidence retrieved', detail: 'A later session retrieves the active fact from hot memory.' },
  { name: 'Foresight', layer: 2, flow: 'read', event: 'Trigger checked', detail: 'Time-sensitive memory is included only when the question makes it relevant.' },
  { name: 'Supersede', layer: 3, flow: 'write', event: 'Old fact retired', detail: 'The previous database fact stays traceable in the graph but is no longer active.' },
];
const STAGE_MS = 1800;

const COMPONENTS = [
  {
    does: 'Remembers across sessions',
    how: 'Observations are consolidated into durable facts that outlive the conversation.',
    part: 'Fast observation storage, slow-path extraction',
  },
  {
    does: 'Applies corrections at once',
    how: 'A correction takes effect in the current session, before consolidation finishes.',
    part: 'Session working set, hot memory',
  },
  {
    does: 'Retires outdated facts',
    how: 'The old value is marked superseded and kept for history. Nothing is silently deleted.',
    part: 'CONTRADICTS and SUPERSEDED_BY edges, validity windows',
  },
  {
    does: 'Raises commitments on time',
    how: 'Deadlines and commitments are recorded, then retrieved when time and context make them relevant.',
    part: 'Foresight records in warm memory',
  },
  {
    does: 'Synthesises reflections',
    how: 'Related memories are summarised once enough supporting evidence has accumulated.',
    part: 'Community detection, reflection synthesis',
  },
  {
    does: 'Retrieves within a budget',
    how: 'Each question is routed to quick, relational or deep retrieval, and lower-priority context is trimmed.',
    part: 'Retrieval router, Chroma vector search, graph traversal',
  },
];

/** evaluation/local/published_summary.json, generated 2026-07-12: 13 cases, 13 passed. */
const EVAL_GROUPS = [
  { name: 'Direct fact recall', checks: 'A specific attribute is recalled from past turns.', passed: 1, total: 1 },
  { name: 'Cross-session recall', checks: 'A verified fact is recalled in a later session.', passed: 1, total: 1 },
  { name: 'Session correction handling', checks: 'A correction is used within the session it was made in.', passed: 1, total: 1 },
  { name: 'Contradiction handling', checks: 'New data that conflicts with stored memory is detected.', passed: 2, total: 2 },
  { name: 'Supersession', checks: 'The outdated fact is replaced in the temporal graph.', passed: 1, total: 1 },
  { name: 'Foresight activation', checks: 'A recorded commitment is raised when it becomes relevant.', passed: 1, total: 1 },
  { name: 'Deep synthesis', checks: 'Reflections are built from clustered memories.', passed: 3, total: 3 },
  { name: 'Routing intent', checks: 'The question is sent to the right retrieval mode.', passed: 2, total: 2 },
  { name: 'Retrieval sufficiency', checks: 'Retrieval stops once the evidence is enough to answer.', passed: 1, total: 1 },
];
const EVAL_PASSED = EVAL_GROUPS.reduce((n, g) => n + g.passed, 0);
const EVAL_TOTAL = EVAL_GROUPS.reduce((n, g) => n + g.total, 0);

const MCP_SPEC = [
  { term: 'Endpoint', value: 'https://mira.ninja/mcp', mono: true },
  { term: 'Transport', value: 'Streamable HTTP' },
  { term: 'Authorization', value: 'OAuth 2.1 + PKCE' },
  { term: 'Data boundary', value: 'Workspace-scoped' },
];

const prefersReducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

function SectionLabel({ index, name }: { index: string; name: string }) {
  return (
    <div className="lp-label">
      <span className="lp-label-index">{index}</span>
      <span>{name}</span>
    </div>
  );
}

export default function Landing() {
  const { setPage, theme, toggleTheme } = useApp();
  const [stage, setStage] = useState(0);
  const [running, setRunning] = useState(false);
  // bumps on every stage change, including re-selecting the same stage, so the graph replays
  const [tick, setTick] = useState(0);
  const figureRef = useRef<HTMLDivElement>(null);
  const autoPlayed = useRef(false);

  const goTo = (index: number) => {
    setStage(index);
    setTick((t) => t + 1);
  };

  useEffect(() => {
    if (!running) return;
    const timer = window.setTimeout(() => {
      if (stage === PIPELINE_STAGES.length - 1) {
        setRunning(false);
        return;
      }
      goTo(stage + 1);
    }, STAGE_MS);
    return () => window.clearTimeout(timer);
  }, [running, stage]);

  const runSequence = () => {
    goTo(0);
    setRunning(true);
  };

  // play the sequence once, the first time the figure is properly on screen
  useEffect(() => {
    const el = figureRef.current;
    if (!el || prefersReducedMotion()) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting || autoPlayed.current) return;
        autoPlayed.current = true;
        setStage(0);
        setTick((t) => t + 1);
        setRunning(true);
        observer.disconnect();
      },
      { threshold: 0.6 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const active = PIPELINE_STAGES[stage];
  const activeLayer = MEMORY_LAYERS[active.layer];
  // layers touched by earlier stages of the walk-through
  const visited = new Set(PIPELINE_STAGES.slice(0, stage).map((s) => s.layer));

  const launch = () => setPage('auth');

  const scrollTo = (id: string, e?: React.MouseEvent) => {
    e?.preventDefault();
    document.getElementById(id)?.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth' });
  };

  return (
    <div className="lp tw">
      <header className="lp-nav">
        <div className="lp-nav-inner">
          <a className="lp-brand" href="#top" onClick={(e) => scrollTo('top', e)}>
            <BrandMark lockup size={24} title="MIRA" />
          </a>
          <nav className="lp-nav-links" aria-label="Sections">
            <a href="#how-it-works" onClick={(e) => scrollTo('how-it-works', e)}>How it works</a>
            <a href="#capabilities" onClick={(e) => scrollTo('capabilities', e)}>Components</a>
            <a href="#results" onClick={(e) => scrollTo('results', e)}>Evaluation</a>
            <a href="#mcp" onClick={(e) => scrollTo('mcp', e)}>MCP</a>
            <a href="/developers/docs">Developers</a>
          </nav>
          <div className="lp-nav-actions">
            <Button
              variant="ghost"
              size="icon"
              onClick={toggleTheme}
              aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
              title="Toggle theme"
            >
              {theme === 'dark' ? <Sun /> : <Moon />}
            </Button>
            <Button variant="outline" onClick={launch}>
              Open MIRA
            </Button>
          </div>
        </div>
      </header>

      <main className="lp-main" id="top">
        <section className="lp-hero">
          <div className="lp-hero-copy">
            <h1 className="lp-hero-title">Agent memory you can inspect.</h1>
            <p className="lp-hero-sub">
              MIRA keeps what a user tells an agent across sessions, retires a fact when it is
              corrected, and records which memories went into each answer.
            </p>
            <div className="lp-hero-actions">
              <Button size="lg" className="lp-cta" onClick={launch}>
                Open the demo
                <ArrowRight data-icon="inline-end" />
              </Button>
              <Button
                variant="link"
                size="lg"
                className="lp-cta-link"
                nativeButton={false}
                render={<a href="#how-it-works" onClick={(e) => scrollTo('how-it-works', e)} />}
              >
                Follow a correction through memory
              </Button>
            </div>
            <p className="lp-hero-stack">SQLite source of truth · Chroma index · typed temporal graph · MCP endpoint</p>
          </div>

          <figure className="lp-trace" aria-label="Example answer trace">
            <figcaption className="lp-trace-head">
              <span>Example trace</span>
              <span>demo workspace</span>
            </figcaption>
            <div className="lp-trace-line">
              <span className="lp-trace-key">asked</span>
              <p>“Which database are we using now?”</p>
            </div>
            <ol className="lp-trace-rows">
              {TRACE_ROWS.map((row) => (
                <li className="lp-trace-row" key={row.label}>
                  <span className="lp-trace-key">{row.label}</span>
                  <div>
                    <strong>{row.value}</strong>
                    <p>{row.detail}</p>
                  </div>
                  <Badge variant="outline" className="font-mono">{row.status}</Badge>
                </li>
              ))}
            </ol>
            <div className="lp-trace-line lp-trace-answer">
              <span className="lp-trace-key">answered</span>
              <p>
                <strong>PostgreSQL.</strong> The newer correction superseded the older MongoDB memory.
              </p>
            </div>
          </figure>
        </section>

        <section className="lp-section" id="how-it-works">
          <SectionLabel index="01" name="How it works" />
          <div className="lp-section-body">
            <h2>One correction, followed through memory.</h2>
            <p className="lp-lede">
              A user says the project moved from MongoDB to PostgreSQL. The fast path saves the turn
              straight away; background processing turns it into durable memory that a later
              session can retrieve.
            </p>

            <div className="lp-figure" ref={figureRef}>
              <div className="lp-figure-bar">
                <ToggleGroup
                  className="lp-stage-group"
                  variant="outline"
                  size="sm"
                  spacing={0}
                  value={[String(stage)]}
                  onValueChange={(next) => {
                    const picked = next[0];
                    setRunning(false);
                    // pressing the current stage again replays it instead of clearing the selection
                    goTo(picked === undefined ? stage : Number(picked));
                  }}
                  aria-label="Memory pipeline stages"
                >
                  {PIPELINE_STAGES.map((s, index) => (
                    <ToggleGroupItem key={s.name} value={String(index)} aria-label={`Stage ${index + 1}: ${s.name}`}>
                      <span className="lp-stage-index">{index + 1}</span>
                      {s.name}
                    </ToggleGroupItem>
                  ))}
                </ToggleGroup>
                <Button variant="outline" size="sm" onClick={runSequence} disabled={running}>
                  {running ? <Play data-icon="inline-start" /> : <RotateCcw data-icon="inline-start" />}
                  {running ? 'Running' : 'Run sequence'}
                </Button>
              </div>

              <div className="lp-figure-stage">
                <MemoryLayerGraph
                  layers={MEMORY_LAYERS}
                  active={active.layer}
                  flow={active.flow}
                  visited={visited}
                  runKey={tick}
                  label={`Stage ${stage + 1} of ${PIPELINE_STAGES.length}, ${active.name}: ${
                    active.flow === 'write' ? 'MIRA writes to' : 'MIRA reads from'
                  } ${activeLayer.title}.`}
                />
              </div>

              <Separator />

              <div className="lp-figure-readout" aria-live="polite">
                <div className="lp-readout-event">
                  <div className="lp-readout-meta">
                    <Badge variant="outline" className="font-mono">
                      <Num value={stage + 1} />/{PIPELINE_STAGES.length}
                    </Badge>
                    <span>{active.flow === 'write' ? 'writes to' : 'reads from'}</span>
                    <Badge className="bg-signal font-mono text-signal-foreground">{activeLayer.level}</Badge>
                    <span>{activeLayer.title}</span>
                  </div>
                  <p>
                    <strong>{active.event}.</strong> {active.detail}
                  </p>
                </div>
                <code className="lp-readout-data">{activeLayer.data}</code>
              </div>
            </div>
          </div>
        </section>

        <section className="lp-section" id="capabilities">
          <SectionLabel index="02" name="Components" />
          <div className="lp-section-body">
            <h2>What it does, and the part that does it.</h2>
            <p className="lp-lede">
              Each behaviour maps to a piece of the running system, so you can open the app and
              look at it working.
            </p>
            <Table className="lp-table">
              <TableHeader>
                <TableRow>
                  <TableHead>Behaviour</TableHead>
                  <TableHead>What happens</TableHead>
                  <TableHead>Implemented by</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {COMPONENTS.map((c) => (
                  <TableRow key={c.does}>
                    <TableCell className="lp-cell-strong">{c.does}</TableCell>
                    <TableCell className="lp-cell-muted">{c.how}</TableCell>
                    <TableCell className="lp-cell-mono">{c.part}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </section>

        <section className="lp-section" id="results">
          <SectionLabel index="03" name="Evaluation" />
          <div className="lp-section-body">
            <h2>
              {EVAL_PASSED} of {EVAL_TOTAL} local regression cases pass.
            </h2>
            <p className="lp-lede">
              Saved cases check the answer, the retrieval mode, the trace evidence and the graph
              behaviour. Summary generated 12 July 2026; live benchmark results are reported
              separately in the app.
            </p>
            <Table className="lp-table">
              <TableHeader>
                <TableRow>
                  <TableHead>Group</TableHead>
                  <TableHead>Checks that</TableHead>
                  <TableHead className="text-right">Passed</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {EVAL_GROUPS.map((g) => (
                  <TableRow key={g.name}>
                    <TableCell className="lp-cell-strong">{g.name}</TableCell>
                    <TableCell className="lp-cell-muted">{g.checks}</TableCell>
                    <TableCell className="text-right">
                      <Badge variant="outline" className="font-mono text-signal">
                        {g.passed}/{g.total}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </section>

        <section className="lp-section" id="mcp">
          <SectionLabel index="04" name="MCP" />
          <div className="lp-section-body">
            <h2>Use the memory tools from an MCP client.</h2>
            <p className="lp-lede">
              Retrieval, graph, foresight and session-memory operations are available through an
              authenticated MCP endpoint. OAuth binds each client to the user’s workspace before
              any memory tool runs.
            </p>
            <Table className="lp-table lp-table-spec">
              <TableBody>
                {MCP_SPEC.map((item) => (
                  <TableRow key={item.term}>
                    <TableHead scope="row">{item.term}</TableHead>
                    <TableCell className={item.mono ? 'lp-cell-code' : undefined}>{item.value}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </section>

        <section className="lp-section lp-close">
          <SectionLabel index="05" name="Try it" />
          <div className="lp-section-body">
            <h2>Send a message and watch where it goes.</h2>
            <p className="lp-lede">
              The demo workspace needs no account. Follow one message through persistence,
              retrieval and graph updates to its answer trace.
            </p>
            <Button size="lg" className="lp-cta" onClick={launch}>
              Open the demo
              <ArrowRight data-icon="inline-end" />
            </Button>
          </div>
        </section>
      </main>

      <footer className="lp-footer">
        <div className="lp-footer-inner">
          <div className="lp-footer-brand">
            <span className="lp-brand">
              <BrandMark lockup size={20} title="MIRA" />
            </span>
            <p>Inspectable memory for AI agents.</p>
          </div>
          <nav className="lp-footer-links" aria-label="Footer">
            <div>
              <span>Page</span>
              <a href="#how-it-works" onClick={(e) => scrollTo('how-it-works', e)}>How it works</a>
              <a href="#capabilities" onClick={(e) => scrollTo('capabilities', e)}>Components</a>
              <a href="#results" onClick={(e) => scrollTo('results', e)}>Evaluation</a>
              <a href="#mcp" onClick={(e) => scrollTo('mcp', e)}>MCP access</a>
              <a href="/developers/docs">Developer docs</a>
            </div>
            <div>
              <span>App</span>
              <button type="button" onClick={launch}>Open workspace</button>
              <button
                type="button"
                onClick={() => {
                  scrollTo('how-it-works');
                  runSequence();
                }}
              >
                Run the sequence
              </button>
              <a href="/sitemap.xml">Sitemap</a>
            </div>
            <div>
              <span>Contact</span>
              <a href="https://github.com/jerrygeorge360" target="_blank" rel="noreferrer">GitHub · jerrygeorge360</a>
              <a href="https://github.com/deltron-fr" target="_blank" rel="noreferrer">GitHub · deltron-fr</a>
            </div>
          </nav>
        </div>
      </footer>
    </div>
  );
}
