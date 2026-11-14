import {
  AlertTriangle,
  Archive,
  Check,
  CheckCircle2,
  ChevronRight,
  Clock3,
  LoaderCircle,
  Moon,
  Play,
  RefreshCw,
  Save,
  SlidersHorizontal,
  Sparkles,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import { formatTime } from '../api/useLiveData';
import { useApp } from '../context/AppContext';

type JsonRecord = Record<string, unknown>;
type ChangeFilter = 'all' | 'reinforced' | 'weakened' | 'archived' | 'forgotten' | 'unchanged';
type SleepStatus = 'pending' | 'running' | 'completed' | 'failed' | 'idle' | 'unknown';

interface SleepConfig {
  enabled: boolean;
  intervalHours: number;
  lastSleepAt?: string;
  nextSleepAt?: string;
  status: SleepStatus;
}

interface MemoryChange {
  id: string;
  kind: ChangeFilter | 'other';
  title: string;
  beforeScore?: number;
  afterScore?: number;
  afterStatus?: string;
}

interface SleepRun {
  id: string;
  trigger: string;
  status: SleepStatus;
  startedAt?: string;
  finishedAt?: string;
  error?: string;
  before: JsonRecord;
  after: JsonRecord;
  summary: JsonRecord;
  changes: MemoryChange[];
  raw: JsonRecord;
}

interface SleepMetric {
  key: string;
  label: string;
  aliases: string[];
  format?: 'count' | 'score';
}

const SLEEP_METRICS: SleepMetric[] = [
  { key: 'active', label: 'Active', aliases: ['active_memories', 'active_memory_count', 'active'] },
  { key: 'weakening', label: 'Weakening', aliases: ['weakening_memories', 'weakening_memory_count', 'weakening', 'weakened'] },
  { key: 'archived', label: 'Archived', aliases: ['archived_memories', 'archived_memory_count', 'archived'] },
  { key: 'forgotten', label: 'Forgotten', aliases: ['forgotten_memories', 'forgotten_memory_count', 'forgotten'] },
  { key: 'pinned', label: 'Pinned', aliases: ['pinned_memories', 'pinned_memory_count', 'pinned'] },
  { key: 'average_retention', label: 'Avg retention', format: 'score', aliases: ['average_retention_score', 'avg_retention_score', 'average_retention', 'retention_score'] },
  { key: 'average_trust', label: 'Avg trust', format: 'score', aliases: ['average_trust', 'avg_trust', 'average_trust_score', 'avg_trust_score'] },
  { key: 'hot', label: 'Hot', aliases: ['hot_memory_count', 'hot_memories', 'hot'] },
  { key: 'warm', label: 'Warm', aliases: ['warm_memory_count', 'warm_memories', 'warm'] },
  { key: 'cold', label: 'Cold', aliases: ['cold_memory_count', 'cold_memories', 'cold'] },
];

const ACTIONS: Array<{ key: string; label: string; aliases: string[] }> = [
  { key: 'reviewed', label: 'reviewed', aliases: ['reviewed_count', 'reviewed'] },
  { key: 'reinforced', label: 'reinforced', aliases: ['reinforced_count', 'reinforced'] },
  { key: 'weakened', label: 'weakened', aliases: ['weakened_count', 'weakened'] },
  { key: 'archived', label: 'archived', aliases: ['archived_count', 'archived'] },
  { key: 'forgotten', label: 'forgotten', aliases: ['forgotten_count', 'forgotten'] },
  { key: 'consolidated', label: 'consolidated', aliases: ['consolidated_count', 'consolidated', 'duplicates_consolidated'] },
];

const FILTERS: Array<{ value: ChangeFilter; label: string }> = [
  { value: 'all', label: 'All' },
  { value: 'reinforced', label: 'Reinforced' },
  { value: 'weakened', label: 'Weakened' },
  { value: 'archived', label: 'Archived' },
  { value: 'forgotten', label: 'Forgotten' },
  { value: 'unchanged', label: 'Unchanged' },
];

export default function MemorySleepPanel() {
  const { memoryRefreshKey } = useApp();
  const [config, setConfig] = useState<SleepConfig | null>(null);
  const [runs, setRuns] = useState<SleepRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedRun, setSelectedRun] = useState<SleepRun | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [intervalHours, setIntervalHours] = useState('6');
  const [changeFilter, setChangeFilter] = useState<ChangeFilter>('all');
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    Promise.all([api.memorySleepConfig(), api.memorySleepRuns({ limit: 12 })])
      .then(([configPayload, runsPayload]) => {
        if (!active) return;
        const nextConfig = normalizeConfig(configPayload);
        const nextRuns = normalizeRuns(runsPayload);
        setConfig(nextConfig);
        setEnabled(nextConfig.enabled);
        setIntervalHours(String(nextConfig.intervalHours));
        setRuns(nextRuns);
        setSelectedRunId((current) => {
          if (current && nextRuns.some((run) => run.id === current)) return current;
          return nextRuns[0]?.id ?? null;
        });
        setSelectedRun((current) => {
          if (current && nextRuns.some((run) => run.id === current.id)) {
            return nextRuns.find((run) => run.id === current.id) ?? current;
          }
          return nextRuns[0] ?? null;
        });
      })
      .catch((requestError: unknown) => {
        if (active) setError(errorMessage(requestError));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [memoryRefreshKey, refreshToken]);

  useEffect(() => {
    if (!selectedRunId || !isActiveStatus(selectedRun?.status ?? 'idle')) return;
    let active = true;
    const poll = window.setInterval(() => {
      api.memorySleepRun(selectedRunId)
        .then((payload) => {
          if (!active) return;
          const nextRun = normalizeRun(payload);
          setSelectedRun(nextRun);
          setRuns((current) => replaceRun(current, nextRun));
          if (!isActiveStatus(nextRun.status)) {
            setRefreshToken((value) => value + 1);
          }
        })
        .catch((requestError: unknown) => {
          if (active) setError(errorMessage(requestError));
        });
    }, 1800);
    return () => {
      active = false;
      window.clearInterval(poll);
    };
  }, [selectedRunId, selectedRun?.status]);

  async function selectRun(run: SleepRun) {
    setSelectedRunId(run.id);
    setSelectedRun(run);
    setChangeFilter('all');
    setError(null);
    if (!run.id) return;
    setDetailLoading(true);
    try {
      const detail = normalizeRun(await api.memorySleepRun(run.id));
      setSelectedRun(detail);
      setRuns((current) => replaceRun(current, detail));
    } catch (requestError: unknown) {
      setError(errorMessage(requestError));
    } finally {
      setDetailLoading(false);
    }
  }

  async function saveSettings() {
    const parsedInterval = Number(intervalHours);
    if (!Number.isFinite(parsedInterval) || parsedInterval < 1 || parsedInterval > 168) {
      setError('Sleep interval must be between 1 and 168 hours.');
      setNotice(null);
      return;
    }
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const response = await api.updateMemorySleepConfig({
        enabled,
        interval_hours: parsedInterval,
      });
      const nextConfig = normalizeConfig(response);
      setConfig(nextConfig);
      setEnabled(nextConfig.enabled);
      setIntervalHours(String(nextConfig.intervalHours));
      setNotice('Sleep settings saved.');
    } catch (requestError: unknown) {
      setError(errorMessage(requestError));
    } finally {
      setSaving(false);
    }
  }

  async function runSleepNow() {
    setRunning(true);
    setError(null);
    setNotice(null);
    try {
      const result = normalizeRun(await api.runMemorySleep());
      setSelectedRun(result);
      setSelectedRunId(result.id || null);
      setRuns((current) => replaceRun(current, result));
      setChangeFilter('all');
      const alreadyRunning = result.raw.status === 'already_running';
      setNotice(alreadyRunning ? (stringFrom(result.raw.message) ?? 'Sleep already running.') : isActiveStatus(result.status) ? 'Sleep started.' : 'Sleep completed.');
      if (!isActiveStatus(result.status)) setRefreshToken((value) => value + 1);
    } catch (requestError: unknown) {
      setError(errorMessage(requestError));
    } finally {
      setRunning(false);
    }
  }

  const status = selectedRun && isActiveStatus(selectedRun.status)
    ? selectedRun.status
    : config?.status ?? 'idle';
  const filteredChanges = useMemo(
    () => (selectedRun?.changes ?? []).filter((change) => changeFilter === 'all' || change.kind === changeFilter).slice(0, 24),
    [changeFilter, selectedRun],
  );
  const metrics = selectedRun ? compareSnapshots(selectedRun.before, selectedRun.after) : [];
  const actionSummary = selectedRun ? summarizeActions(selectedRun) : [];
  const hasSnapshot = metrics.length > 0;

  return (
    <section className="memory-sleep-shell" aria-labelledby="memory-sleep-title">
      <div className="memory-sleep-panel memory-sleep-controls-panel">
        <div className="memory-sleep-heading">
          <div className="health-section-head">
            <Moon size={17} />
            <div>
              <h3 id="memory-sleep-title">Memory Sleep</h3>
              <p>Schedule bounded lifecycle maintenance and inspect exactly what changed.</p>
            </div>
          </div>
          <StatusPill status={status} />
        </div>

        <div className="memory-sleep-control-grid">
          <div className="memory-sleep-setting-card">
            <div className="memory-sleep-setting-label">
              <SlidersHorizontal size={15} />
              <span>Automatic sleep</span>
            </div>
            <label className="memory-sleep-switch-row">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(event) => setEnabled(event.target.checked)}
                disabled={loading || saving}
              />
              <span className="memory-sleep-switch" aria-hidden="true" />
              <strong>{enabled ? 'On' : 'Off'}</strong>
            </label>
            <p>Runs from the worker when the configured interval is due.</p>
          </div>

          <div className="memory-sleep-setting-card">
            <label className="memory-sleep-setting-label" htmlFor="sleep-interval">
              <Clock3 size={15} />
              <span>Sleep every</span>
            </label>
            <div className="memory-sleep-number-input">
              <input
                id="sleep-interval"
                type="number"
                min="1"
                max="168"
                step="1"
                value={intervalHours}
                onChange={(event) => setIntervalHours(event.target.value)}
                disabled={loading || saving}
              />
              <span>hours</span>
            </div>
            <p>Choose a whole number from 1 to 168.</p>
          </div>

          <div className="memory-sleep-schedule-card">
            <ScheduleValue label="Last sleep" value={config?.lastSleepAt} />
            <ScheduleValue label="Next sleep" value={enabled ? config?.nextSleepAt : undefined} emptyLabel={enabled ? 'Not scheduled' : 'Automatic sleep is off'} />
          </div>
        </div>

        <div className="memory-sleep-actions">
          <button type="button" className="memory-sleep-button secondary" onClick={saveSettings} disabled={loading || saving}>
            {saving ? <LoaderCircle size={15} className="spin" /> : <Save size={15} />}
            {saving ? 'Saving…' : 'Save Settings'}
          </button>
          <button type="button" className="memory-sleep-button primary" onClick={runSleepNow} disabled={loading || running || isActiveStatus(status)}>
            {running || isActiveStatus(status) ? <LoaderCircle size={15} className="spin" /> : <Play size={15} />}
            {running || isActiveStatus(status) ? 'Sleep running…' : 'Run Sleep Now'}
          </button>
          {config?.lastSleepAt && <span className="memory-sleep-updated">Last completed {formatSleepTimestamp(config.lastSleepAt)}</span>}
        </div>

        {error && (
          <div className="memory-sleep-message error" role="alert">
            <AlertTriangle size={15} />
            <span>{error}</span>
          </div>
        )}
        {notice && !error && (
          <div className="memory-sleep-message success" role="status">
            <Check size={15} />
            <span>{notice}</span>
          </div>
        )}
      </div>

      <div className="memory-sleep-detail-grid">
        <section className="memory-sleep-panel memory-sleep-latest-panel">
          <div className="memory-sleep-panel-title">
            <Sparkles size={16} />
            <div>
              <h3>{selectedRun?.status === 'failed' ? 'Sleep failure' : 'Latest sleep'}</h3>
              <p>{selectedRun ? `${titleCase(selectedRun.trigger)} · ${formatSleepStatus(selectedRun.status)}` : 'No sleep runs yet.'}</p>
            </div>
            {detailLoading && <LoaderCircle size={15} className="spin memory-sleep-detail-loader" />}
          </div>

          {!selectedRun ? (
            <div className="memory-sleep-empty">Run sleep manually or wait for the first scheduled cycle.</div>
          ) : (
            <>
              {selectedRun.error && (
                <div className="memory-sleep-run-error" role="alert">
                  <AlertTriangle size={14} />
                  <span>{selectedRun.error}</span>
                </div>
              )}
              {hasSnapshot ? (
                <div className="memory-sleep-snapshot" aria-label="Before and after memory snapshot">
                  <div className="memory-sleep-snapshot-head"><span>Memory snapshot</span><b>Before</b><b>After</b></div>
                  {metrics.map((metric) => (
                    <div className="memory-sleep-snapshot-row" key={metric.key}>
                      <span>{metric.label}</span>
                      <strong>{formatMetric(metric.before, metric.format)}</strong>
                      <strong>{formatMetric(metric.after, metric.format)}</strong>
                      <Delta before={metric.before} after={metric.after} />
                    </div>
                  ))}
                </div>
              ) : (
                <div className="memory-sleep-empty">This run did not return before/after snapshot metrics.</div>
              )}
              {actionSummary.length > 0 && (
                <div className="memory-sleep-action-summary">
                  <span>Actions taken</span>
                  <div>
                    {actionSummary.map((action) => <b key={action.label}>{action.value} {action.label}</b>)}
                  </div>
                </div>
              )}
            </>
          )}
        </section>

        <section className="memory-sleep-panel memory-sleep-history-panel">
          <div className="memory-sleep-panel-title">
            <RefreshCw size={16} />
            <div>
              <h3>Recent sleep runs</h3>
              <p>{loading ? 'Loading history…' : `${runs.length} recent ${runs.length === 1 ? 'run' : 'runs'}`}</p>
            </div>
          </div>
          {runs.length === 0 ? (
            <div className="memory-sleep-empty">No sleep history is available yet.</div>
          ) : (
            <div className="memory-sleep-run-list">
              {runs.map((run, index) => (
                <button
                  type="button"
                  key={run.id || `${run.startedAt || 'run'}-${index}`}
                  className={`memory-sleep-run-row${selectedRunId === run.id ? ' selected' : ''}`}
                  onClick={() => selectRun(run)}
                >
                  <span className={`memory-sleep-run-dot ${run.status}`} />
                  <span className="memory-sleep-run-time">
                    <strong>{formatSleepTimestamp(run.startedAt)}</strong>
                    <small>{titleCase(run.trigger)}</small>
                  </span>
                  <span className="memory-sleep-run-summary">{runSummary(run)}</span>
                  <span className={`memory-sleep-status-text ${run.status}`}>{formatSleepStatus(run.status)}</span>
                  <ChevronRight size={15} />
                </button>
              ))}
            </div>
          )}
        </section>
      </div>

      {selectedRun && (
        <section className="memory-sleep-panel memory-sleep-changes-panel">
          <div className="memory-sleep-panel-title memory-sleep-changes-heading">
            <Archive size={16} />
            <div>
              <h3>Changed memories</h3>
              <p>Inspect the compact delta returned for this run.</p>
            </div>
            <div className="memory-sleep-filter-row" role="tablist" aria-label="Memory change filters">
              {FILTERS.map((filter) => (
                <button
                  type="button"
                  key={filter.value}
                  role="tab"
                  aria-selected={changeFilter === filter.value}
                  className={changeFilter === filter.value ? 'active' : ''}
                  onClick={() => setChangeFilter(filter.value)}
                >
                  {filter.label}
                </button>
              ))}
            </div>
          </div>
          {selectedRun.changes.length === 0 ? (
            <div className="memory-sleep-empty">No per-memory change details were returned for this run.</div>
          ) : filteredChanges.length === 0 ? (
            <div className="memory-sleep-empty">No {changeFilter} memories were returned for this run.</div>
          ) : (
            <div className="memory-sleep-change-list">
              {filteredChanges.map((change) => <ChangeCard key={change.id} change={change} />)}
            </div>
          )}
        </section>
      )}
    </section>
  );
}

function ScheduleValue({ label, value, emptyLabel = 'Not recorded' }: { label: string; value?: string; emptyLabel?: string }) {
  return (
    <div className="memory-sleep-schedule-value">
      <span>{label}</span>
      <strong>{value ? formatSleepTimestamp(value) : emptyLabel}</strong>
    </div>
  );
}

function StatusPill({ status }: { status: SleepStatus }) {
  const active = isActiveStatus(status);
  return (
    <span className={`memory-sleep-status-pill ${status}`}>
      {active && <LoaderCircle size={13} className="spin" />}
      {!active && status === 'completed' && <CheckCircle2 size={13} />}
      {!active && status === 'failed' && <AlertTriangle size={13} />}
      {!active && !['completed', 'failed'].includes(status) && <span className="memory-sleep-status-dot" />}
      {active ? 'Running…' : formatSleepStatus(status)}
    </span>
  );
}

function Delta({ before, after }: { before?: number; after?: number }) {
  if (before === undefined || after === undefined || before === after) return <span className="memory-sleep-delta neutral">—</span>;
  const increase = after > before;
  return (
    <span className={`memory-sleep-delta ${increase ? 'increase' : 'decrease'}`}>
      {increase ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
      {formatSigned(after - before)}
    </span>
  );
}

function ChangeCard({ change }: { change: MemoryChange }) {
  const icon = change.kind === 'reinforced' ? <TrendingUp size={14} /> : change.kind === 'weakened' ? <TrendingDown size={14} /> : change.kind === 'unchanged' ? <Check size={14} /> : <Archive size={14} />;
  return (
    <article className={`memory-sleep-change-card ${change.kind}`}>
      <div className="memory-sleep-change-icon">{icon}</div>
      <div className="memory-sleep-change-copy">
        <div className="memory-sleep-change-meta"><span>{titleCase(change.kind)}</span>{change.afterStatus && <small>{change.afterStatus}</small>}</div>
        <strong>{change.title}</strong>
        {(change.beforeScore !== undefined || change.afterScore !== undefined) && (
          <p>Retention: {formatMetric(change.beforeScore, 'score')} → {formatMetric(change.afterScore, 'score')}</p>
        )}
      </div>
    </article>
  );
}

function normalizeConfig(payload: unknown): SleepConfig {
  const root = asRecord(payload);
  const nested = asRecord(root.config);
  const record = Object.keys(nested).length > 0 ? nested : root;
  return {
    enabled: booleanFrom(firstDefined(record.automatic_sleep_enabled, record.enabled), false),
    intervalHours: clampInterval(numberFrom(firstDefined(record.sleep_interval_hours, record.interval_hours), 6)),
    lastSleepAt: stringFrom(firstDefined(record.last_sleep_at, record.last_sleep, record.last_completed_at)),
    nextSleepAt: stringFrom(firstDefined(record.next_sleep_at, record.next_run_at)),
    status: normalizeStatus(record.status),
  };
}

function normalizeRuns(payload: unknown): SleepRun[] {
  const root = asRecord(payload);
  const candidates = Array.isArray(payload)
    ? payload
    : asArray(firstDefined(root.runs, root.items, root.sleep_runs, root.results));
  return candidates.map(normalizeRun).sort((a, b) => timestampValue(b.startedAt) - timestampValue(a.startedAt));
}

function normalizeRun(payload: unknown): SleepRun {
  const root = asRecord(payload);
  const nested = asRecord(firstDefined(root.sleep_run, root.run, root.sleep));
  const record = Object.keys(nested).length > 0 ? nested : root;
  const summary = asRecord(record.summary);
  const snapshots = asRecord(record.snapshots);
  const before = asRecord(firstDefined(record.before, record.before_snapshot, snapshots.before));
  const after = asRecord(firstDefined(record.after, record.after_snapshot, snapshots.after));
  const changeSource = firstDefined(record.changes, record.changed_memories, record.memory_changes, record.deltas);
  return {
    id: stringFrom(firstDefined(record.sleep_run_id, record.run_id, record.id)) ?? '',
    trigger: stringFrom(firstDefined(record.trigger, record.source)) ?? 'manual',
    status: normalizeRunStatus(record),
    startedAt: stringFrom(firstDefined(record.started_at, record.started, record.created_at)),
    finishedAt: stringFrom(firstDefined(record.finished_at, record.completed_at, record.finished)),
    error: stringFrom(firstDefined(record.error, record.failure, record.message && record.status === 'failed' ? record.message : undefined)),
    before,
    after,
    summary,
    changes: normalizeChanges(changeSource),
    raw: record,
  };
}

function normalizeChanges(source: unknown): MemoryChange[] {
  const rows: Array<{ value: unknown; kind?: string }> = [];
  if (Array.isArray(source)) {
    rows.push(...source.map((value) => ({ value })));
  } else {
    const record = asRecord(source);
    for (const kind of ['reinforced', 'weakened', 'archived', 'forgotten', 'unchanged']) {
      const values = asArray(record[kind]);
      rows.push(...values.map((value) => ({ value, kind })));
    }
    const otherRows = asArray(firstDefined(record.items, record.records, record.changes));
    rows.push(...otherRows.map((value) => ({ value })));
  }
  return rows.map((row, index) => {
    const record = asRecord(row.value);
    const memory = asRecord(firstDefined(record.memory, record.record, record.item));
    const sourceRecord = Object.keys(memory).length > 0 ? memory : record;
    const kind = normalizeChangeKind(row.kind ?? stringFrom(firstDefined(record.kind, record.type, record.action, record.change_type, record.status_change)));
    return {
      id: stringFrom(firstDefined(record.id, sourceRecord.id)) ?? `change-${index}`,
      kind,
      title: stringFrom(firstDefined(sourceRecord.content, sourceRecord.text, sourceRecord.title, sourceRecord.summary, sourceRecord.id)) ?? 'Untitled memory',
      beforeScore: optionalNumber(firstDefined(record.retention_before, record.before_retention, record.score_before, record.before_score, sourceRecord.retention_before)),
      afterScore: optionalNumber(firstDefined(record.retention_after, record.after_retention, record.score_after, record.after_score, sourceRecord.retention_after)),
      afterStatus: stringFrom(firstDefined(record.after_status, record.status_after, sourceRecord.lifecycle_status, sourceRecord.status)),
    };
  });
}

function compareSnapshots(before: JsonRecord, after: JsonRecord): Array<{ key: string; label: string; before?: number; after?: number; format?: 'count' | 'score' }> {
  return SLEEP_METRICS.flatMap((metric) => {
    const beforeValue = snapshotValue(before, metric.aliases);
    const afterValue = snapshotValue(after, metric.aliases);
    if (beforeValue === undefined && afterValue === undefined) return [];
    return [{ key: metric.key, label: metric.label, before: beforeValue, after: afterValue, format: metric.format ?? 'count' }];
  });
}

function snapshotValue(snapshot: JsonRecord, aliases: string[]): number | undefined {
  const containers = [snapshot, asRecord(snapshot.metrics), asRecord(snapshot.counts), asRecord(snapshot.statuses)];
  for (const container of containers) {
    for (const alias of aliases) {
      const value = optionalNumber(container[alias]);
      if (value !== undefined) return value;
    }
  }
  return undefined;
}

function summarizeActions(run: SleepRun): Array<{ label: string; value: number }> {
  const containers = [run.raw, run.summary, asRecord(run.summary.actions), asRecord(run.raw.counts)];
  return ACTIONS.flatMap((action) => {
    for (const container of containers) {
      for (const alias of action.aliases) {
        const value = optionalNumber(container[alias]);
        if (value !== undefined) return [{ label: action.label, value }];
      }
    }
    return [];
  });
}

function runSummary(run: SleepRun): string {
  const actions = summarizeActions(run).filter(({ label }) => ['weakened', 'archived', 'forgotten'].includes(label));
  if (actions.length > 0) return actions.map((action) => `${action.value} ${action.label}`).join(' · ');
  if (run.error) return 'Failed';
  return run.status === 'running' || run.status === 'pending' ? 'In progress' : 'No changes reported';
}

function replaceRun(runs: SleepRun[], next: SleepRun): SleepRun[] {
  if (!next.id) return runs;
  const found = runs.some((run) => run.id === next.id);
  const updated = found ? runs.map((run) => run.id === next.id ? next : run) : [next, ...runs];
  return updated.sort((a, b) => timestampValue(b.startedAt) - timestampValue(a.startedAt));
}

function normalizeChangeKind(value: string | undefined): MemoryChange['kind'] {
  const normalized = (value ?? '').toLowerCase();
  if (normalized.includes('reinfor') || normalized.includes('strength')) return 'reinforced';
  if (normalized.includes('weaken') || normalized.includes('demot')) return 'weakened';
  if (normalized.includes('archiv')) return 'archived';
  if (normalized.includes('forget')) return 'forgotten';
  if (normalized.includes('unchang') || normalized.includes('same')) return 'unchanged';
  return 'other';
}

function normalizeStatus(value: unknown): SleepStatus {
  const normalized = String(value ?? 'idle').toLowerCase();
  if (normalized === 'pending' || normalized === 'queued') return 'pending';
  if (normalized === 'running' || normalized === 'in_progress' || normalized === 'processing' || normalized === 'already_running') return 'running';
  if (normalized === 'completed' || normalized === 'complete' || normalized === 'success' || normalized === 'succeeded') return 'completed';
  if (normalized === 'failed' || normalized === 'error') return 'failed';
  return normalized === 'idle' ? 'idle' : 'unknown';
}

function normalizeRunStatus(record: JsonRecord): SleepStatus {
  if (record.status !== undefined && record.status !== null) return normalizeStatus(record.status);
  if (record.finished_at || record.completed_at || record.reviewed !== undefined || record.lifecycle) return 'completed';
  return 'idle';
}

function isActiveStatus(status: SleepStatus): boolean {
  return status === 'pending' || status === 'running';
}

function formatSleepStatus(status: SleepStatus): string {
  if (status === 'completed') return 'Completed';
  if (status === 'failed') return 'Failed';
  if (status === 'pending') return 'Pending';
  if (status === 'running') return 'Running';
  if (status === 'unknown') return 'Unknown';
  return 'Idle';
}

function formatMetric(value: number | undefined, format: 'count' | 'score' = 'count'): string {
  if (value === undefined) return '—';
  if (format === 'score') return value <= 1 ? value.toFixed(2) : `${value.toFixed(1)}%`;
  return value.toLocaleString();
}

function formatSigned(value: number): string {
  return `${value > 0 ? '+' : ''}${Number.isInteger(value) ? value : value.toFixed(2)}`;
}

function formatSleepTimestamp(value?: string): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return formatTime(value) || value;
  return date.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function timestampValue(value?: string): number {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function titleCase(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (character) => character.toUpperCase());
}

function clampInterval(value: number): number {
  return Math.min(168, Math.max(1, Math.round(value || 6)));
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) {
    const detail = error.message.match(/^API \d+:\s*(.*)$/)?.[1];
    if (detail) {
      try {
        const parsed = JSON.parse(detail) as JsonRecord;
        if (typeof parsed.detail === 'string') return parsed.detail;
      } catch {
        return detail;
      }
      return detail;
    }
    return error.message;
  }
  return 'The sleep request failed.';
}

function asRecord(value: unknown): JsonRecord {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as JsonRecord : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function firstDefined(...values: unknown[]): unknown {
  return values.find((value) => value !== undefined && value !== null);
}

function stringFrom(value: unknown): string | undefined {
  return typeof value === 'string' && value ? value : undefined;
}

function numberFrom(value: unknown, fallback: number): number {
  const parsed = optionalNumber(value);
  return parsed ?? fallback;
}

function optionalNumber(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() && Number.isFinite(Number(value))) return Number(value);
  return undefined;
}

function booleanFrom(value: unknown, fallback: boolean): boolean {
  if (typeof value === 'boolean') return value;
  if (typeof value === 'string') {
    if (value.toLowerCase() === 'true') return true;
    if (value.toLowerCase() === 'false') return false;
  }
  return fallback;
}
