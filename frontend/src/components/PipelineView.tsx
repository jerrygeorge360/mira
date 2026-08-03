import {
  AlertTriangle,
  CheckCircle,
  CircleDashed,
  Clock,
  Database,
  FileText,
  Gauge,
  GitBranch,
  Layers,
  PackageCheck,
  Sparkles,
  Waypoints,
  Zap,
} from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import { api } from '../api/client';
import { useLiveData } from '../api/useLiveData';
import { useApp } from '../context/AppContext';
import { ViewStatus } from './ViewStatus';

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
  const [pollTick, setPollTick] = useState(0);
  const { data, status } = useLiveData(
    () => api.memoryLifecycle({ session_id: sessionId ?? undefined, limit: 20 }),
    [sessionId, memoryRefreshKey, pollTick],
  );
  const rows = (data?.items ?? []) as LifecycleRow[];
  const hasActiveWork = rows.some(row => {
    const slowPath = asRecord(row.slow_path);
    const queue = asRecord(slowPath.queue);
    return ['pending', 'processing', 'claimed', 'retrying'].includes(
      text(slowPath.status, text(queue.status)).toLowerCase(),
    );
  });

  useEffect(() => {
    if (!hasActiveWork) return undefined;
    const timer = window.setInterval(() => setPollTick(value => value + 1), 2000);
    return () => window.clearInterval(timer);
  }, [hasActiveWork]);

  return (
    <>
      <div className="view-header">
        <h2>Memory Pipeline</h2>
        <p>
          Fast persistence, session extraction, background consolidation, and durable artifacts
          for recent turns{sessionId ? ' in this conversation' : ''}.
        </p>
      </div>

      {rows.length === 0 ? (
        <ViewStatus
          status={status}
          emptyLabel="No lifecycle activity yet."
          hint="Send a live chat message, then return here to inspect what the memory pipeline produced."
        />
      ) : (
        <div className="pipeline-list">
          {rows.map((row, index) => (
            <LifecycleCard key={observationId(row) || index} row={row} />
          ))}
        </div>
      )}
    </>
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
  const llmUsage = asRecord(slowPath.llm_usage);
  const llmOperations = asRecordArray(llmUsage.operations);
  const rejections = asRecordArray(row.rejections);
  const slowStatus = text(slowPath.status, text(queue.status, 'unknown'));
  const totalArtifacts = ARTIFACTS.reduce((sum, [key]) => sum + number(artifacts[key]), 0);

  return (
    <article className="pipeline-card">
      <div className="pipeline-card-top">
        <div>
          <div className="trace-kicker">{text(observation.role, 'turn')} · {shortId(text(observation.id))}</div>
          <h3>{preview(text(observation.content, 'No content recorded.'), 140)}</h3>
          <p>
            Persisted {formatTime(text(observation.created_at))}. Queue status:{' '}
            <strong>{labelize(slowStatus)}</strong>.
          </p>
        </div>
        <StatusBadge status={slowStatus} />
      </div>

      <div className="pipeline-stages">
        <Stage
          icon={<Zap size={16} />}
          title="Fast persistence"
          status={text(row.fast_path?.status, 'completed')}
          body="Raw observation saved before model-dependent memory work runs."
          meta={row.fast_path?.queued ? 'Queued for background processing' : 'Not queued'}
        />
        <Stage
          icon={<Layers size={16} />}
          title="Session extraction"
          status={text(sessionExtraction.status, 'unknown')}
          body={sessionSummary(asRecord(sessionExtraction.counts))}
          meta={`${asRecordArray(sessionExtraction.items).length} working-set item${asRecordArray(sessionExtraction.items).length === 1 ? '' : 's'}`}
        />
        <Stage
          icon={<Database size={16} />}
          title="Background consolidation"
          status={slowStatus}
          body={`${steps.length} slow-path step${steps.length === 1 ? '' : 's'} journaled.`}
          meta={queue.updated_at ? `Updated ${formatTime(text(queue.updated_at))}` : undefined}
          danger={slowStatus.includes('failed') || slowStatus === 'dead_letter' || slowStatus === 'quarantined'}
        />
        <Stage
          icon={<PackageCheck size={16} />}
          title="Durable artifacts"
          status={totalArtifacts > 0 ? 'produced' : 'none'}
          body={`${totalArtifacts} artifact${totalArtifacts === 1 ? '' : 's'} linked to this turn.`}
          meta={rejections.length ? `${rejections.length} rejection/error signal${rejections.length === 1 ? '' : 's'}` : 'No stored errors'}
          danger={rejections.length > 0}
        />
      </div>

      {number(llmUsage.calls) > 0 ? (
        <div className="pipeline-usage">
          <Gauge size={17} />
          <div>
            <strong>Slow-path model usage</strong>
            <span>
              {number(llmUsage.calls)} call{number(llmUsage.calls) === 1 ? '' : 's'} ·{' '}
              {number(llmUsage.input_tokens).toLocaleString()} input ·{' '}
              {number(llmUsage.output_tokens).toLocaleString()} output
            </span>
          </div>
          <div className="pipeline-usage-measurement">
            <strong>
              {number(llmUsage.provider_measured_calls)}/{number(llmUsage.calls)} measured
            </strong>
            {number(llmUsage.paritok_calls) > 0 ? (
              <span className="chat-token-saving">
                Paritok saved {number(llmUsage.gateway_tokens_saved).toLocaleString()}
                {compressionPercent(llmUsage)}
              </span>
            ) : <span>Direct provider</span>}
          </div>
        </div>
      ) : null}

      <div className="pipeline-artifact-grid">
        {ARTIFACTS.map(([key, label, Icon]) => (
          <div className="pipeline-artifact" key={key}>
            <Icon size={15} />
            <span>{label}</span>
            <strong>{number(artifacts[key])}</strong>
          </div>
        ))}
      </div>

      <details className="pipeline-details">
        <summary>Step journal and artifact ids</summary>
        <div className="pipeline-detail-columns">
          <div>
            <h4>Slow-path steps</h4>
            {steps.length ? (
              <ul className="pipeline-step-list">
                {steps.map((step) => (
                  <li key={`${step.step_name}-${step.updated_at}`}>
                    <span>{labelize(text(step.step_name))}</span>
                    <strong className={step.last_error ? 'danger' : ''}>{labelize(text(step.status))}</strong>
                    {step.last_error ? <small>{text(step.last_error)}</small> : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p>No slow-path step journal entries yet.</p>
            )}
            {llmOperations.length ? (
              <>
                <h4>Model operations</h4>
                <ul className="pipeline-step-list">
                  {llmOperations.map(operation => (
                    <li key={text(operation.name)}>
                      <span>{labelize(text(operation.name))}</span>
                      <strong>{number(operation.input_tokens).toLocaleString()} in</strong>
                      <small>
                        {number(operation.calls)} call{number(operation.calls) === 1 ? '' : 's'} ·{' '}
                        {number(operation.output_tokens).toLocaleString()} out
                        {number(operation.gateway_tokens_saved) > 0
                          ? ` · ${number(operation.gateway_tokens_saved).toLocaleString()} saved`
                          : ''}
                      </small>
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
          </div>
          <div>
            <h4>Artifact ids</h4>
            <pre>{JSON.stringify(artifactIds, null, 2)}</pre>
          </div>
        </div>
      </details>
    </article>
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
    <div className={`pipeline-stage${danger ? ' danger' : ''}`}>
      <div className="pipeline-stage-icon">{icon}</div>
      <div>
        <div className="pipeline-stage-head">
          <h4>{title}</h4>
          <span>{labelize(status)}</span>
        </div>
        <p>{body}</p>
        {meta ? <small>{meta}</small> : null}
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const failed = status.includes('failed') || status === 'dead_letter' || status === 'quarantined';
  const completed = status === 'completed' || status === 'done';
  const Icon = failed ? AlertTriangle : completed ? CheckCircle : CircleDashed;
  return (
    <div className={`pipeline-status-badge${failed ? ' danger' : completed ? ' ok' : ''}`}>
      <Icon size={15} />
      {labelize(status)}
    </div>
  );
}

function sessionSummary(counts: Record<string, unknown>) {
  const entries = Object.entries(counts).filter(([, value]) => number(value) > 0);
  if (!entries.length) return 'No session working-set item was extracted from this turn.';
  return entries
    .map(([key, value]) => `${number(value)} ${labelize(key).toLowerCase()}`)
    .join(' · ');
}

function compressionPercent(usage: Record<string, unknown>): string {
  const original = number(usage.gateway_input_tokens_original);
  if (original <= 0) return '';
  const percent = Math.round((number(usage.gateway_tokens_saved) / original) * 100);
  return ` (${percent}%)`;
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
