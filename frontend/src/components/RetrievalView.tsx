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
import { Eyebrow, KeyValue, KeyValueList, Panel, Stat, StatStrip, ViewHeader, ViewPage } from './view';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty';

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
    <ViewPage>
      <ViewHeader
        title="Retrieval Trace"
        description="How MIRA selected memory, assembled context, and checked whether it had enough evidence."
      />
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
    </ViewPage>
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
    <Empty className="border">
      <EmptyHeader>
        <EmptyTitle>{hasTrace ? 'The last answer did not use retrieved evidence' : 'No query trace yet'}</EmptyTitle>
        <EmptyDescription>
          A trace shows the route MIRA chose (quick, relational, deep, or a general answer that bypasses
          memory), the candidates it considered, the prompt sections it assembled, and whether the
          evidence was sufficient.
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button variant="outline" onClick={onOpenChat}>
          Ask a memory question
        </Button>
      </EmptyContent>
    </Empty>
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
    <section className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <Eyebrow>Last answer trace</Eyebrow>
        <h3 className="text-lg font-medium text-pretty">{trace.query ? String(trace.query) : 'Query unavailable'}</h3>
        <p className="text-sm text-muted-foreground">
          MIRA used <span className="font-medium text-foreground">{modeLabel(trace.retrieval_mode)}</span> retrieval and
          assembled {sectionCount || 'no'} prompt section{sectionCount === 1 ? '' : 's'} from the available memory sources.
        </p>
      </div>
      <StatStrip>
        <Stat label="Route" value={modeLabel(trace.retrieval_mode)} />
        <Stat
          label="Sufficiency"
          value={sufficiencyLabel(sufficient)}
          tone={sufficient === false ? 'destructive' : sufficient ? 'signal' : undefined}
        />
        <Stat label="Candidates" value={String(candidateCount || evidence.length)} />
        <Stat label="Selected" value={String(selectedCount)} />
        <Stat label="Prompt sections" value={String(sectionCount)} />
        <Stat label="Created" value={<span className="text-base">{formatTime(trace.created_at)}</span>} />
      </StatStrip>
    </section>
  );
}

function TracePipeline({ trace, evidence }: { trace: TraceData; evidence: Row[] }) {
  const sufficiency = trace.sufficiency;
  const sufficient = sufficiency ? Boolean(sufficiency.is_sufficient ?? sufficiency.sufficient) : null;
  const promptSections = trace.prompt_sections ?? [];
  const candidates = retrievalLogRecords(evidence).length || evidence.length;
  const stages = [
    {
      icon: <MessageSquare />,
      title: 'Query received',
      body: trace.query ? String(trace.query) : 'The user message was persisted as the trace anchor.',
      meta: trace.user_observation_id ? `Observation ${shortId(String(trace.user_observation_id))}` : undefined,
    },
    {
      icon: <Route />,
      title: 'Route selected',
      body: `${modeLabel(trace.retrieval_mode)} retrieval was used for this turn.`,
      meta: trace.retrieval_log_id ? `Retrieval log ${shortId(String(trace.retrieval_log_id))}` : undefined,
    },
    {
      icon: <Search />,
      title: 'Candidates retrieved',
      body: `${candidates} candidate record${candidates === 1 ? '' : 's'} were available for ranking or inspection.`,
      meta: evidenceBreakdown(evidence),
    },
    {
      icon: <Layers />,
      title: 'Context assembled',
      body: `${promptSections.length} prompt section${promptSections.length === 1 ? '' : 's'} were built from session, durable, and retrieved memory.`,
      meta: promptSections.map((section) => String(section.section ?? 'section')).join(' · ') || undefined,
    },
    {
      icon: <CheckCircle />,
      title: 'Sufficiency checked',
      body: sufficiencyText(sufficiency),
      meta: sufficient === null ? 'No sufficiency verdict recorded' : sufficient ? 'Passed' : 'Needs more evidence',
    },
  ];

  return (
    // the five stages of one retrieval, in order, as one strip
    <ol
      className="grid overflow-hidden rounded-xl border bg-card sm:grid-cols-2 lg:grid-cols-5 *:border-b *:last:border-b-0 sm:*:border-r lg:*:border-b-0 lg:*:last:border-r-0"
      aria-label="Retrieval stages"
    >
      {stages.map((stage, index) => (
        <li key={stage.title} className="flex min-w-0 flex-col gap-1.5 p-3 text-xs">
          <div className="flex items-center gap-2 [&_svg]:size-3.5 [&_svg]:shrink-0 [&_svg]:text-muted-foreground">
            <span className="font-mono text-faint tabular-nums">{index + 1}</span>
            {stage.icon}
            <h4 className="min-w-0 flex-1 truncate font-medium">{stage.title}</h4>
          </div>
          <p className="line-clamp-4 text-pretty text-muted-foreground">{stage.body}</p>
          {stage.meta && <p className="font-mono text-[11px] text-pretty text-faint">{stage.meta}</p>}
        </li>
      ))}
    </ol>
  );
}

function EvidenceStory({ evidence }: { evidence: Row[] }) {
  if (!evidence.length) return null;
  return (
    <Panel title="Evidence timeline" description="Every record the trace kept, in the order it was recorded.">
      <ol className="flex flex-col *:border-b *:last:border-b-0">
        {evidence.map((row, index) => {
          const kind = evidenceKind(row);
          const record = objectRecord(row.record);
          const title = evidenceTitle(row, record);
          const id = String(row.id ?? record?.source_id ?? record?.id ?? '');
          const recordSource = String(record?.source ?? '');
          return (
            <li key={`${kind}-${index}`} className="grid grid-cols-[1.5rem_minmax(0,1fr)_auto] gap-x-3 py-3 first:pt-0 last:pb-0">
              <span className="pt-0.5 font-mono text-faint tabular-nums">{index + 1}</span>
              <div className="flex min-w-0 flex-col gap-1">
                <div className="flex items-center gap-2 [&_svg]:size-3.5 [&_svg]:shrink-0 [&_svg]:text-muted-foreground">
                  {iconForKind(kind)}
                  <Eyebrow>{KIND_LABELS[kind]}</Eyebrow>
                </div>
                <p className="text-sm font-medium text-pretty wrap-break-word">{title}</p>
                <p className="text-muted-foreground">{KIND_COPY[kind]}</p>
                <Collapsible>
                  <CollapsibleTrigger render={<Button variant="ghost" size="xs" className="-ml-2" />}>
                    Advanced
                  </CollapsibleTrigger>
                  <CollapsibleContent className="flex flex-col gap-2 pt-2">
                    <KeyValueList className="max-w-md">
                      <KeyValue label="Source">{String(row.source ?? kind)}</KeyValue>
                      {id && <KeyValue label="ID">{id}</KeyValue>}
                      <KeyValue label="Score">{score(row.score ?? record?.score)}</KeyValue>
                      {recordSource && <KeyValue label="Record source">{recordSource}</KeyValue>}
                    </KeyValueList>
                    <pre className="max-h-64 overflow-auto rounded-lg border bg-background p-3 font-mono text-xs text-muted-foreground">
                      {JSON.stringify(row, null, 2)}
                    </pre>
                  </CollapsibleContent>
                </Collapsible>
              </div>
              <Badge variant="outline" className="font-mono tabular-nums" title="Score">
                {score(row.score ?? record?.score)}
              </Badge>
            </li>
          );
        })}
      </ol>
    </Panel>
  );
}

function evidenceKind(row: Row): EvidenceKind {
  const source = String(row.source ?? '');
  if (source in KIND_LABELS) return source as EvidenceKind;
  return 'unknown';
}

function iconForKind(kind: EvidenceKind) {
  if (kind === 'retrieval_log') return <Search />;
  if (kind === 'observation') return <FileText />;
  if (kind === 'atomic_fact') return <Boxes />;
  if (kind === 'session_item') return <Layers />;
  if (kind === 'working_memory') return <Flame />;
  if (kind === 'graph_path') return <GitBranch />;
  if (kind === 'community_summary') return <Brain />;
  return <FileText />;
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
