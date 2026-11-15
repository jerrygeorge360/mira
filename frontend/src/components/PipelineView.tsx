import {
  AlertTriangle,
  CheckCircle,
  CircleDashed,
  Clock,
  Database,
  FileText,
  GitBranch,
  Layers,
  PackageCheck,
  Sparkles,
  Waypoints,
  Zap,
} from 'lucide-react';
import type { ReactNode } from 'react';
import { api } from '../api/client';
import { useLiveData } from '../api/useLiveData';
import { useApp } from '../context/AppContext';
import { ViewStatus } from './ViewStatus';
import PipelineJournal from './PipelineJournal';
import { Eyebrow, ViewHeader, ViewPage } from './view';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

type LifecycleRow = {
  observation?: Record<string, unknown>;
  fast_path?: Record<string, unknown>;
  session_extraction?: Record<string, unknown>;
  slow_path?: Record<string, unknown>;
  artifacts?: Record<string, unknown>;
  artifact_ids?: Record<string, unknown>;
  rejections?: unknown[];
};

const ARTIFACTS = [
  ['atomic_facts', 'Atomic facts', FileText],
  ['entities', 'Entities', Waypoints],
  ['graph_edges', 'Graph edges', GitBranch],
  ['foresight_records', 'Foresight', Clock],
  ['reflections', 'Reflections', Sparkles],
  ['working_memory', 'Hot memory', PackageCheck],
] as const;

export default function PipelineView() {
  const { sessionId, memoryRefreshKey } = useApp();
  const { data, status } = useLiveData(
    () => api.memoryLifecycle({ session_id: sessionId ?? undefined, limit: 20 }),
    [sessionId, memoryRefreshKey],
  );
  const rows = (data?.items ?? []) as LifecycleRow[];

  return (
    <ViewPage>
      <ViewHeader
        title="Memory Pipeline"
        description={`Fast persistence, session extraction, background consolidation, and durable artifacts for recent turns${
          sessionId ? ' in this conversation' : ''
        }.`}
      />

      {rows.length === 0 ? (
        <ViewStatus
          status={status}
          emptyLabel="No lifecycle activity yet."
          hint="Send a live chat message, then return here to inspect what the memory pipeline produced."
        />
      ) : (
        <div className="flex flex-col gap-4">
          {rows.map((row, index) => (
            <LifecycleCard key={observationId(row) || index} row={row} />
          ))}
        </div>
      )}
    </ViewPage>
  );
}

function LifecycleCard({ row }: { row: LifecycleRow }) {
  const observation = asRecord(row.observation);
  const slowPath = asRecord(row.slow_path);
  const queue = asRecord(slowPath.queue);
  const sessionExtraction = asRecord(row.session_extraction);
  const artifacts = asRecord(row.artifacts);
  const artifactIds = asRecord(row.artifact_ids);
  const steps = asRecordArray(slowPath.steps);
  const rejections = asRecordArray(row.rejections);
  const slowStatus = text(slowPath.status, text(queue.status, 'unknown'));
  const totalArtifacts = ARTIFACTS.reduce((sum, [key]) => sum + number(artifacts[key]), 0);

  return (
    <Card>
      <CardHeader>
        <Eyebrow>{text(observation.role, 'turn')} · {shortId(text(observation.id))}</Eyebrow>
        <CardTitle className="text-sm text-pretty">{preview(text(observation.content, 'No content recorded.'), 140)}</CardTitle>
        <CardDescription>Persisted {formatTime(text(observation.created_at))}</CardDescription>
        <CardAction>
          <StatusBadge status={slowStatus} />
        </CardAction>
      </CardHeader>

      {/* the four stages of one turn, left to right, as one strip */}
      <CardContent className="flex flex-col gap-4">
      <ol className="grid overflow-hidden rounded-lg border sm:grid-cols-2 lg:grid-cols-4 *:border-b *:last:border-b-0 sm:*:border-r lg:*:border-b-0 lg:*:last:border-r-0">
        <Stage
          icon={<Zap />}
          title="Fast persistence"
          status={text(row.fast_path?.status, 'completed')}
          body="Raw observation saved before model-dependent memory work runs."
          meta={row.fast_path?.queued ? 'Queued for background processing' : 'Not queued'}
        />
        <Stage
          icon={<Layers />}
          title="Session extraction"
          status={text(sessionExtraction.status, 'unknown')}
          body={sessionSummary(asRecord(sessionExtraction.counts))}
          meta={`${asRecordArray(sessionExtraction.items).length} working-set item${asRecordArray(sessionExtraction.items).length === 1 ? '' : 's'}`}
        />
        <Stage
          icon={<Database />}
          title="Background consolidation"
          status={slowStatus}
          body={`${steps.length} slow-path step${steps.length === 1 ? '' : 's'} journaled.`}
          meta={queue.updated_at ? `Updated ${formatTime(text(queue.updated_at))}` : undefined}
          danger={slowStatus.includes('failed') || slowStatus === 'dead_letter' || slowStatus === 'quarantined'}
        />
        <Stage
          icon={<PackageCheck />}
          title="Durable artifacts"
          status={totalArtifacts > 0 ? 'produced' : 'none'}
          body={`${totalArtifacts} artifact${totalArtifacts === 1 ? '' : 's'} linked to this turn.`}
          meta={rejections.length ? `${rejections.length} rejection/error signal${rejections.length === 1 ? '' : 's'}` : 'No stored errors'}
          danger={rejections.length > 0}
        />
      </ol>

      <dl className="grid grid-cols-2 gap-x-6 sm:grid-cols-3 lg:grid-cols-6">
        {ARTIFACTS.map(([key, label, Icon]) => {
          const count = number(artifacts[key]);
          return (
            <div className="flex items-center gap-2 border-b py-2 lg:border-b-0" key={key}>
              <Icon className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
              <dt className="min-w-0 flex-1 truncate text-muted-foreground">{label}</dt>
              <dd className={cn('font-mono font-medium tabular-nums', count > 0 ? 'text-signal' : 'text-faint')}>{count}</dd>
            </div>
          );
        })}
      </dl>
      </CardContent>

      <PipelineJournal steps={steps} artifactIds={artifactIds} artifactLabels={ARTIFACTS} />
    </Card>
  );
}

function Stage({
  icon,
  title,
  status,
  body,
  meta,
  danger = false,
}: {
  icon: ReactNode;
  title: string;
  status: string;
  body: string;
  meta?: string;
  danger?: boolean;
}) {
  return (
    <li className="flex min-w-0 flex-col gap-1.5 p-3">
      <div className="flex items-center gap-2 [&_svg]:size-3.5 [&_svg]:shrink-0 [&_svg]:text-muted-foreground">
        {icon}
        <h4 className="min-w-0 flex-1 truncate font-medium">{title}</h4>
      </div>
      <span className={cn('font-mono text-[11px] tracking-wider uppercase', danger ? 'text-destructive' : 'text-faint')}>
        {labelize(status)}
      </span>
      <p className="text-pretty text-muted-foreground">{body}</p>
      {meta ? <p className={cn('font-mono text-[11px]', danger ? 'text-destructive' : 'text-faint')}>{meta}</p> : null}
    </li>
  );
}

function StatusBadge({ status }: { status: string }) {
  const failed = status.includes('failed') || status === 'dead_letter' || status === 'quarantined';
  const completed = status === 'completed' || status === 'done';
  const Icon = failed ? AlertTriangle : completed ? CheckCircle : CircleDashed;
  return (
    <Badge variant={failed ? 'destructive' : 'outline'} className={completed ? 'text-signal' : undefined}>
      <Icon data-icon="inline-start" />
      {labelize(status)}
    </Badge>
  );
}

function sessionSummary(counts: Record<string, unknown>) {
  const entries = Object.entries(counts).filter(([, value]) => number(value) > 0);
  if (!entries.length) return 'No session working-set item was extracted from this turn.';
  return entries
    .map(([key, value]) => `${number(value)} ${labelize(key).toLowerCase()}`)
    .join(' · ');
}

function observationId(row: LifecycleRow) {
  return text(asRecord(row.observation).id);
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function asRecordArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.map(asRecord) : [];
}

function text(value: unknown, fallback = '') {
  return typeof value === 'string' && value ? value : fallback;
}

function number(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function preview(value: string, max: number) {
  return value.length <= max ? value : `${value.slice(0, max - 1)}…`;
}

function shortId(value: string) {
  return value ? value.slice(0, 8) : 'unknown';
}

function labelize(value: string) {
  return (value || 'unknown').replaceAll('_', ' ');
}

function formatTime(value: string) {
  if (!value) return 'time unknown';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}
