import {
  Boxes,
  Brain,
  CheckCircle,
  FileText,
  Flame,
  GitBranch,
  Layers,
  MessageSquare,
  Route,
  Search,
} from 'lucide-react';
import { api } from '../api/client';
import { useApp } from '../context/AppContext';
import { useLiveData } from '../api/useLiveData';
import { ViewStatus } from './ViewStatus';

type Row = Record<string, unknown>;

interface TraceData extends Row {
  trace_id?: string;
  session_id?: string;
  retrieval_mode?: string;
  query?: string | null;
  retrieved_observation_ids?: string[];
  retrieved_fact_ids?: string[];
  session_item_ids?: string[];
  hot_memory_ids?: string[];
  graph_path_ids?: string[];
  community_summary_ids?: string[];
  sufficiency?: Row | null;
  prompt_sections?: Row[];
  hydration_ids?: string[];
  retrieval_log_id?: string | null;
  prompt_log_id?: string | null;
  created_at?: string | null;
  evidence?: Row[];
}

type EvidenceKind =
  | 'retrieval_log'
  | 'observation'
  | 'atomic_fact'
  | 'session_item'
  | 'working_memory'
  | 'graph_path'
  | 'community_summary'
  | 'unknown';

const KIND_LABELS: Record<EvidenceKind, string> = {
  retrieval_log: 'Candidate retrieval',
  observation: 'Durable observation',
  atomic_fact: 'Structured fact',
  session_item: 'Session working set',
  working_memory: 'Hot memory injected',
  graph_path: 'Graph relationship',
  community_summary: 'Community memory',
  unknown: 'Trace record',
};

const KIND_COPY: Record<EvidenceKind, string> = {
  retrieval_log: 'The retriever returned ranked candidates for this query.',
  observation: 'A persisted conversation observation was considered as evidence.',
  atomic_fact: 'A structured fact extracted by the slow path was considered.',
  session_item: 'A current-session memory item was included in the working context.',
  working_memory: 'A promoted hot-memory item was injected into context.',
  graph_path: 'A typed graph relationship was used as relational evidence.',
  community_summary: 'A graph-derived community summary contributed broad context.',
  unknown: 'A trace item was recorded for inspection.',
};

function score(value: unknown): string {
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(2) : '—';
}

export default function RetrievalView() {
  const { lastTraceId, setView, memoryRefreshKey } = useApp();
  const { data, status } = useLiveData(
    () => (lastTraceId ? api.retrievalTrace(lastTraceId) : Promise.reject(new Error('no trace'))),
    [lastTraceId, memoryRefreshKey],
  );
  const trace = data as TraceData | null;
  const evidence = trace?.evidence ?? [];

  return (
    <div>
      <div className="view-header">
        <h2>Retrieval Trace</h2>
        <p>How MIRA selected memory, assembled context, and checked whether it had enough evidence.</p>
      </div>
      {!trace || !lastTraceId ? (
        <RetrievalEmpty
          status={lastTraceId ? status : 'live'}
          hasTrace={Boolean(lastTraceId)}
          onOpenChat={() => setView('Chat')}
        />
      ) : (
        <>
          <TraceSummary trace={trace} evidence={evidence} />
          <TracePipeline trace={trace} evidence={evidence} />
          <EvidenceStory evidence={evidence} />
        </>
      )}
    </div>
  );
}

function RetrievalEmpty({
  status,
  hasTrace,
  onOpenChat,
}: {
  status: 'loading' | 'live' | 'offline';
  hasTrace: boolean;
  onOpenChat: () => void;
}) {
  if (status !== 'live') {
    return (
      <ViewStatus
        status={status}
        emptyLabel="No retrieval evidence available."
        hint="Ask MIRA a memory question to generate a trace."
      />
    );
  }
  return (
    <section className="empty-inspector retrieval-empty">
      <div className="empty-inspector-main">
        <div className="trace-kicker">Answer trace</div>
        <h3>{hasTrace ? 'The last answer did not use retrieved evidence' : 'No query trace yet'}</h3>
        <p>
          Retrieval traces show the route MIRA chose, the candidates it considered, prompt
          sections it assembled, and whether the evidence was sufficient for the answer.
        </p>
        <button type="button" onClick={onOpenChat}>Ask a memory question</button>
      </div>
      <div className="empty-inspector-grid wide">
        <EmptyMetric label="Quick" value="recent and direct memory" />
        <EmptyMetric label="Deep" value="synthesis and communities" />
        <EmptyMetric label="Relational" value="graph paths and edges" />
        <EmptyMetric label="General" value="memory bypass" />
        <EmptyMetric label="Sufficiency" value="evidence check" />
        <EmptyMetric label="Prompt sections" value="budgeted context" />
      </div>
    </section>
  );
}

function EmptyMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="empty-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function TraceSummary({ trace, evidence }: { trace: TraceData; evidence: Row[] }) {
  const sufficiency = trace.sufficiency;
  const sufficient = sufficiency ? Boolean(sufficiency.is_sufficient ?? sufficiency.sufficient) : null;
  const selectedCount =
    asList(trace.retrieved_observation_ids).length
    + asList(trace.retrieved_fact_ids).length
    + asList(trace.session_item_ids).length
    + asList(trace.hot_memory_ids).length
    + asList(trace.graph_path_ids).length
    + asList(trace.community_summary_ids).length;
  const candidateCount = retrievalLogRecords(evidence).length;
  const sectionCount = (trace.prompt_sections ?? []).length;

  return (
    <section className="trace-summary-panel">
      <div className="trace-summary-main">
        <div className="trace-kicker">Last answer trace</div>
        <h3>{trace.query ? String(trace.query) : 'Query unavailable'}</h3>
        <p>
          MIRA used <strong>{modeLabel(trace.retrieval_mode)}</strong> retrieval and assembled
          {' '}{sectionCount || 'no'} prompt section{sectionCount === 1 ? '' : 's'} from the available memory sources.
        </p>
      </div>
      <div className="trace-summary-grid">
        <SummaryStat label="Route" value={modeLabel(trace.retrieval_mode)} />
        <SummaryStat label="Sufficiency" value={sufficiencyLabel(sufficient)} tone={sufficient === false ? 'warn' : 'ok'} />
        <SummaryStat label="Candidates" value={String(candidateCount || evidence.length)} />
        <SummaryStat label="Selected" value={String(selectedCount)} />
        <SummaryStat label="Prompt sections" value={String(sectionCount)} />
        <SummaryStat label="Created" value={formatTime(trace.created_at)} />
      </div>
    </section>
  );
}

function TracePipeline({ trace, evidence }: { trace: TraceData; evidence: Row[] }) {
  const sufficiency = trace.sufficiency;
  const sufficient = sufficiency ? Boolean(sufficiency.is_sufficient ?? sufficiency.sufficient) : null;
  const promptSections = trace.prompt_sections ?? [];
  const stages = [
    {
      icon: <MessageSquare size={16} />,
      title: 'Query received',
      body: trace.query ? String(trace.query) : 'The user message was persisted as the trace anchor.',
      meta: trace.user_observation_id ? `Observation ${shortId(String(trace.user_observation_id))}` : undefined,
    },
    {
      icon: <Route size={16} />,
      title: 'Route selected',
      body: `${modeLabel(trace.retrieval_mode)} retrieval was used for this turn.`,
      meta: trace.retrieval_log_id ? `Retrieval log ${shortId(String(trace.retrieval_log_id))}` : undefined,
    },
    {
      icon: <Search size={16} />,
      title: 'Candidates retrieved',
      body: `${retrievalLogRecords(evidence).length || evidence.length} candidate record${(retrievalLogRecords(evidence).length || evidence.length) === 1 ? '' : 's'} were available for ranking or inspection.`,
      meta: evidenceBreakdown(evidence),
    },
    {
      icon: <Layers size={16} />,
      title: 'Context assembled',
      body: `${promptSections.length} prompt section${promptSections.length === 1 ? '' : 's'} were built from session, durable, and retrieved memory.`,
      meta: promptSections.map((section) => String(section.section ?? 'section')).join(' · ') || undefined,
    },
    {
      icon: <CheckCircle size={16} />,
      title: 'Sufficiency checked',
      body: sufficiencyText(sufficiency),
      meta: sufficient === null ? 'No sufficiency verdict recorded' : sufficient ? 'Passed' : 'Needs more evidence',
    },
  ];

  return (
    <section className="trace-pipeline" aria-label="Retrieval stages">
      {stages.map((stage, index) => (
        <div key={stage.title} className="trace-stage">
          <div className="trace-stage-icon">{stage.icon}</div>
          <div className="trace-stage-body">
            <div className="trace-stage-count">{index + 1}</div>
            <h4>{stage.title}</h4>
            <p>{stage.body}</p>
            {stage.meta && <small>{stage.meta}</small>}
          </div>
        </div>
      ))}
    </section>
  );
}

function EvidenceStory({ evidence }: { evidence: Row[] }) {
  if (!evidence.length) return null;
  return (
    <section className="retrieval-story">
      <div className="results-section-title">Evidence timeline</div>
      <div className="retrieval-evidence">
        {evidence.map((row, index) => {
          const kind = evidenceKind(row);
          const record = objectRecord(row.record);
          const title = evidenceTitle(row, record);
          return (
            <article key={`${kind}-${index}`} className={`evidence-card evidence-${kind}`}>
              <div className="evidence-rank">{index + 1}</div>
              <div className="evidence-icon">{iconForKind(kind)}</div>
              <div className="evidence-meta">
                <div className="evidence-kind">{KIND_LABELS[kind]}</div>
                <div className="evidence-title">{title}</div>
                <div className="evidence-source">{KIND_COPY[kind]}</div>
                <details className="evidence-details">
                  <summary>Advanced</summary>
                  <div className="trace-detail-grid">
                    <Detail label="Source" value={String(row.source ?? kind)} />
                    <Detail label="ID" value={String(row.id ?? record?.source_id ?? record?.id ?? '')} />
                    <Detail label="Score" value={score(row.score ?? record?.score)} />
                    <Detail label="Record source" value={String(record?.source ?? '')} />
                  </div>
                  <pre>{JSON.stringify(row, null, 2)}</pre>
                </details>
              </div>
              <div className="evidence-score">{score(row.score ?? record?.score)}</div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function SummaryStat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: 'ok' | 'warn';
}) {
  return (
    <div className={`trace-summary-stat${tone ? ` ${tone}` : ''}`}>
      <span>{label}</span>
      <strong>{value || '—'}</strong>
    </div>
  );
}

function Detail({ label, value }: { label: string; value?: string }) {
  if (!value) return null;
  return (
    <>
      <span>{label}</span>
      <strong>{value}</strong>
    </>
  );
}

function evidenceKind(row: Row): EvidenceKind {
  const source = String(row.source ?? '');
  if (source in KIND_LABELS) return source as EvidenceKind;
  return 'unknown';
}

function iconForKind(kind: EvidenceKind) {
  if (kind === 'retrieval_log') return <Search size={16} />;
  if (kind === 'observation') return <FileText size={16} />;
  if (kind === 'atomic_fact') return <Boxes size={16} />;
  if (kind === 'session_item') return <Layers size={16} />;
  if (kind === 'working_memory') return <Flame size={16} />;
  if (kind === 'graph_path') return <GitBranch size={16} />;
  if (kind === 'community_summary') return <Brain size={16} />;
  return <FileText size={16} />;
}

function evidenceTitle(row: Row, record?: Row): string {
  const content = record?.content ?? record?.text ?? record?.summary ?? row.content;
  if (typeof content === 'string' && content.trim()) return content;
  const relation = record?.relation ?? record?.edge_type;
  if (relation) return String(relation);
  const sourceId = row.id ?? row.source_id ?? record?.source_id ?? record?.id;
  return sourceId ? shortId(String(sourceId)) : 'Recorded trace item';
}

function retrievalLogRecords(evidence: Row[]): Row[] {
  return evidence.filter((row) => row.source === 'retrieval_log');
}

function evidenceBreakdown(evidence: Row[]): string {
  const counts = new Map<string, number>();
  for (const row of evidence) {
    const label = KIND_LABELS[evidenceKind(row)];
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return Array.from(counts.entries()).map(([label, count]) => `${count} ${label}`).join(' · ');
}

function sufficiencyText(value: Row | null | undefined): string {
  if (!value) return 'No sufficiency check was recorded for this answer.';
  const sufficient = Boolean(value.is_sufficient ?? value.sufficient);
  const missing = asList(value.missing ?? value.gaps);
  if (sufficient) return 'The retrieved context was judged sufficient for the answer.';
  if (missing.length) return `The first pass was missing: ${missing.join(', ')}.`;
  return 'The trace recorded an insufficient-context verdict.';
}

function sufficiencyLabel(value: boolean | null): string {
  if (value === null) return 'Not recorded';
  return value ? 'Passed' : 'Needs retry';
}

function modeLabel(value: unknown): string {
  const mode = String(value ?? 'quick').trim();
  return mode ? `${mode.charAt(0).toUpperCase()}${mode.slice(1)}` : 'Quick';
}

function formatTime(value: unknown): string {
  if (typeof value !== 'string' || !value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function shortId(value: string): string {
  return value.length > 18 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value;
}

function asList(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}

function objectRecord(value: unknown): Row | undefined {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Row : undefined;
}
