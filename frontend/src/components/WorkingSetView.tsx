import {
  ArrowRight,
  CheckCircle,
  Clock,
  FileText,
  Flame,
  Layers,
  MessageSquare,
  Shield,
} from 'lucide-react';
import { api } from '../api/client';
import { useApp } from '../context/AppContext';
import { useLiveData } from '../api/useLiveData';
import { ViewStatus } from './ViewStatus';

type Row = Record<string, unknown>;

const ACTIVE_GROUPS = [
  { key: 'corrections', title: 'Active corrections', types: ['correction'], statuses: ['provisional', 'hydrated', 'confirmed'], icon: Shield },
  { key: 'constraints', title: 'Constraints', types: ['active_constraint', 'current_goal'], statuses: ['provisional', 'hydrated', 'confirmed'], icon: Layers },
  { key: 'decisions', title: 'Decisions', types: ['decision'], statuses: ['provisional', 'hydrated', 'confirmed'], icon: CheckCircle },
  { key: 'questions', title: 'Open questions', types: ['open_question'], statuses: ['provisional', 'hydrated', 'confirmed'], icon: MessageSquare },
  { key: 'pending', title: 'Pending promotion', promotion: ['eligible', 'pending_confirmation'], icon: Flame },
] as const;

const INACTIVE_STATUSES = ['resolved', 'expired', 'rejected', 'superseded'];

export default function WorkingSetView() {
  const { sessionId, setView, memoryRefreshKey } = useApp();
  const { data, status } = useLiveData(
    () => (sessionId ? api.sessionWorkingSet(sessionId) : Promise.reject(new Error('no session'))),
    [sessionId, memoryRefreshKey],
  );
  const rows = (data?.items as Row[] | undefined) ?? [];
  const activeRows = rows.filter((row) => !INACTIVE_STATUSES.includes(text(row.status)));
  const inactiveRows = rows.filter((row) => INACTIVE_STATUSES.includes(text(row.status)));

  return (
    <div>
      <div className="view-header">
        <h2>Session Working Set</h2>
        <p>Current-session memory that can steer the next answer, with source, usage, and promotion evidence.</p>
      </div>
      {activeRows.length === 0 ? (
        <WorkingSetEmpty
          status={sessionId ? status : 'live'}
          hasSession={Boolean(sessionId)}
          onOpenChat={() => setView('Chat')}
        />
      ) : (
        <div className="working-set-sections">
          {ACTIVE_GROUPS.map((group) => {
            const items = activeRows.filter((row) => groupKey(row) === group.key);
            if (items.length === 0) return null;
            const Icon = group.icon;
            return (
              <section className="working-set-section" key={group.key}>
                <div className="working-set-section-head">
                  <Icon size={16} />
                  <h3>{group.title}</h3>
                  <span>{items.length}</span>
                </div>
                <div className="working-set-grid">
                  {items.map((item) => <WorkingSetCard key={String(item.id)} item={item} />)}
                </div>
              </section>
            );
          })}
        </div>
      )}
      {inactiveRows.length > 0 ? (
        <details className="working-set-history">
          <summary>
            <Clock size={16} />
            <span>Inactive history</span>
            <strong>{inactiveRows.length}</strong>
          </summary>
          <p>Resolved, expired, rejected, and superseded items are retained for inspection but cannot steer answers.</p>
          <div className="working-set-grid">
            {inactiveRows.map((item) => <WorkingSetCard key={String(item.id)} item={item} />)}
          </div>
        </details>
      ) : null}
    </div>
  );
}

function WorkingSetEmpty({
  status,
  hasSession,
  onOpenChat,
}: {
  status: 'loading' | 'live' | 'offline';
  hasSession: boolean;
  onOpenChat: () => void;
}) {
  if (status !== 'live') {
    return (
      <ViewStatus
        status={status}
        emptyLabel="No working-set items."
        hint="Corrections, constraints, decisions, and open questions appear here as you talk to MIRA."
      />
    );
  }
  return (
    <section className="empty-inspector">
      <div className="empty-inspector-main">
        <div className="trace-kicker">Session micro-path</div>
        <h3>{hasSession ? 'No active working-set items' : 'No live session yet'}</h3>
        <p>
          This page shows memory that can affect the next answer immediately, before the
          slow-path worker turns it into durable facts, graph edges, reflections, or foresight.
        </p>
        <button type="button" onClick={onOpenChat}>Open Chat</button>
      </div>
      <div className="empty-inspector-grid">
        <EmptyMetric label="Corrections" value="direct fixes" />
        <EmptyMetric label="Constraints" value="active rules" />
        <EmptyMetric label="Decisions" value="project choices" />
        <EmptyMetric label="Promotion" value="hot-memory eligibility" />
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

function WorkingSetCard({ item }: { item: Row }) {
  const source = firstRecord(item.source_messages);
  const supersededItems = asRows(item.superseded_items);
  const durable = asRows(item.durable_memory);
  const usageCount = number(item.usage_count);
  const priority = priorityLabel(number(item.priority));

  return (
    <article className={`working-card ${active(item) ? '' : 'inactive'}`}>
      <div className="working-card-main">
        <div>
          <div className="trace-kicker">{labelize(text(item.type))}</div>
          <h4>{text(item.content, 'No content recorded.')}</h4>
        </div>
        <span className={`working-priority ${priority.toLowerCase()}`}>{priority}</span>
      </div>

      <div className="working-field-grid">
        <Field label="Scope" value={labelize(text(item.scope))} />
        <Field label="Status" value={labelize(text(item.status))} />
        <Field label="Origin" value={labelize(text(item.origin))} />
        <Field label="Explicitness" value={labelize(text(item.explicitness_label))} />
        <Field label="Created" value={formatTime(text(item.created_at))} />
        <Field label="Expires" value={item.expires_at ? formatTime(text(item.expires_at)) : 'End of session'} />
        <Field label="Used" value={`${usageCount} response${usageCount === 1 ? '' : 's'}`} />
        <Field label="Tokens" value={`${number(item.token_cost)}`} />
        <Field label="Promotion" value={labelize(text(item.promotion_status))} />
        <Field label="Durable" value={durable.length ? `${durable.length} hot item${durable.length === 1 ? '' : 's'}` : 'Not promoted'} />
      </div>

      <div className="working-source-row">
        <FileText size={15} />
        <div>
          <span>Source</span>
          <strong>{sourceLabel(source)}</strong>
        </div>
      </div>

      {text(item.evidence_span) ? (
        <blockquote className="working-evidence">{text(item.evidence_span)}</blockquote>
      ) : null}

      {supersededItems.length > 0 ? (
        <div className="working-supersedes">
          <ArrowRight size={15} />
          <div>
            <span>Supersedes</span>
            {supersededItems.map((row) => (
              <strong key={String(row.id)}>{text(row.content, String(row.id))}</strong>
            ))}
          </div>
        </div>
      ) : null}

      <details className="working-details">
        <summary>Usage and raw fields</summary>
        <pre>{JSON.stringify({
          id: item.id,
          source_observations: item.source_observations,
          used_in_responses: item.used_in_responses,
          durable_memory: item.durable_memory,
          resolution_reason: item.resolution_reason,
        }, null, 2)}</pre>
      </details>
    </article>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="working-field">
      <span>{label}</span>
      <strong>{value || 'Unknown'}</strong>
    </div>
  );
}

function groupKey(row: Row) {
  const type = text(row.type);
  const status = text(row.status);
  const promotion = text(row.promotion_status);
  if (['eligible', 'pending_confirmation'].includes(promotion)) return 'pending';
  const group = ACTIVE_GROUPS.find(candidate => (
    'types' in candidate
    && candidate.types?.includes(type as never)
    && candidate.statuses?.includes(status as never)
  ));
  return group?.key ?? null;
}

function active(item: Row) {
  return item.active === true || ['provisional', 'hydrated', 'confirmed'].includes(text(item.status));
}

function firstRecord(value: unknown): Row | null {
  const rows = asRows(value);
  return rows[0] ?? null;
}

function asRows(value: unknown): Row[] {
  return Array.isArray(value)
    ? value.filter((item): item is Row => Boolean(item) && typeof item === 'object' && !Array.isArray(item))
    : [];
}

function sourceLabel(source: Row | null) {
  if (!source) return 'No source message attached';
  const index = number(source.message_index);
  const content = text(source.content);
  return `Message ${index || '?'} · ${preview(content, 92)}`;
}

function priorityLabel(value: number) {
  if (value >= 0.66) return 'High';
  if (value >= 0.33) return 'Medium';
  return 'Low';
}

function text(value: unknown, fallback = '') {
  return typeof value === 'string' && value ? value : fallback;
}

function number(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function labelize(value: string) {
  return (value || 'unknown').replaceAll('_', ' ');
}

function preview(value: string, max: number) {
  return value.length <= max ? value : `${value.slice(0, max - 1)}…`;
}

function formatTime(value: string) {
  if (!value) return 'Unknown';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}
