import {
  AlertTriangle,
  Archive,
  Check,
  CheckCircle2,
  ChevronRight,
  Moon,
  Play,
  RefreshCw,
  Save,
  Sparkles,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import { formatTime } from '../api/useLiveData';
import { useApp } from '../context/AppContext';
import { Eyebrow, KeyValue, KeyValueList, Num, Panel, SCORE_FORMAT } from './view';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Field, FieldDescription, FieldLabel } from '@/components/ui/field';
import { InputGroup, InputGroupAddon, InputGroupInput, InputGroupText } from '@/components/ui/input-group';
import { Spinner } from '@/components/ui/spinner';
import { Switch } from '@/components/ui/switch';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';

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

  const busy = running || isActiveStatus(status);

  return (
    <section className="flex flex-col gap-4" aria-labelledby="memory-sleep-title">
      <Panel
        title={<span id="memory-sleep-title">Memory Sleep</span>}
        icon={<Moon />}
        description="Schedule bounded lifecycle maintenance and inspect exactly what changed."
        action={<StatusPill status={status} />}
        contentClassName="flex flex-col gap-4"
      >
        <div className="grid gap-x-8 gap-y-5 md:grid-cols-3">
          <Field>
            <FieldLabel htmlFor="sleep-automatic">Automatic sleep</FieldLabel>
            <div className="flex items-center gap-2.5">
              <Switch
                id="sleep-automatic"
                checked={enabled}
                onCheckedChange={setEnabled}
                disabled={loading || saving}
              />
              <span className="font-mono text-xs">{enabled ? 'On' : 'Off'}</span>
            </div>
            <FieldDescription>Runs from the worker when the configured interval is due.</FieldDescription>
          </Field>

          <Field>
            <FieldLabel htmlFor="sleep-interval">Sleep every</FieldLabel>
            <InputGroup className="w-36">
              <InputGroupInput
                id="sleep-interval"
                type="number"
                min="1"
                max="168"
                step="1"
                value={intervalHours}
                onChange={(event) => setIntervalHours(event.target.value)}
                disabled={loading || saving}
              />
              <InputGroupAddon align="inline-end">
                <InputGroupText>hours</InputGroupText>
              </InputGroupAddon>
            </InputGroup>
            <FieldDescription>Choose a whole number from 1 to 168.</FieldDescription>
          </Field>

          <KeyValueList>
            <KeyValue label="Last sleep">{config?.lastSleepAt ? formatSleepTimestamp(config.lastSleepAt) : 'Not recorded'}</KeyValue>
            <KeyValue label="Next sleep">
              {enabled
                ? config?.nextSleepAt
                  ? formatSleepTimestamp(config.nextSleepAt)
                  : 'Not scheduled'
                : 'Automatic sleep is off'}
            </KeyValue>
          </KeyValueList>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" onClick={saveSettings} disabled={loading || saving}>
            {saving ? <Spinner data-icon="inline-start" /> : <Save data-icon="inline-start" />}
            {saving ? 'Saving…' : 'Save settings'}
          </Button>
          <Button onClick={runSleepNow} disabled={loading || busy}>
            {busy ? <Spinner data-icon="inline-start" /> : <Play data-icon="inline-start" />}
            {busy ? 'Sleep running…' : 'Run sleep now'}
          </Button>
        </div>

        {error && (
          <Alert variant="destructive">
            <AlertTriangle />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {notice && !error && (
          <Alert role="status">
            <Check />
            <AlertDescription>{notice}</AlertDescription>
          </Alert>
        )}
      </Panel>

      <div className="grid items-start gap-4 lg:grid-cols-2">
        <Panel
          title={selectedRun?.status === 'failed' ? 'Sleep failure' : 'Latest sleep'}
          icon={<Sparkles />}
          description={
            selectedRun ? `${titleCase(selectedRun.trigger)} · ${formatSleepStatus(selectedRun.status)}` : 'No sleep runs yet.'
          }
          action={detailLoading ? <Spinner /> : undefined}
          contentClassName="flex flex-col gap-4"
        >
          {!selectedRun ? (
            <p className="text-muted-foreground">Run sleep manually or wait for the first scheduled cycle.</p>
          ) : (
            <>
              {selectedRun.error && (
                <Alert variant="destructive">
                  <AlertTriangle />
                  <AlertDescription>{selectedRun.error}</AlertDescription>
                </Alert>
              )}
              {hasSnapshot ? (
                <Table aria-label="Before and after memory snapshot">
                  <TableHeader>
                    <TableRow>
                      <TableHead>Memory snapshot</TableHead>
                      <TableHead className="text-right">Before</TableHead>
                      <TableHead className="text-right">After</TableHead>
                      <TableHead className="text-right">Change</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {metrics.map((metric) => (
                      <TableRow key={metric.key}>
                        <TableCell>{metric.label}</TableCell>
                        <TableCell className="text-right font-mono"><Metric value={metric.before} format={metric.format} /></TableCell>
                        <TableCell className="text-right font-mono"><Metric value={metric.after} format={metric.format} /></TableCell>
                        <TableCell className="text-right">
                          <Delta before={metric.before} after={metric.after} />
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : (
                <p className="text-muted-foreground">This run did not return before/after snapshot metrics.</p>
              )}
              {actionSummary.length > 0 && (
                <div className="flex flex-col gap-2">
                  <Eyebrow>Actions taken</Eyebrow>
                  <div className="flex flex-wrap gap-1.5">
                    {actionSummary.map((action) => (
                      <Badge variant="secondary" className="font-mono" key={action.label}>
                        {action.value} {action.label}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </Panel>

        <Panel
          title="Recent sleep runs"
          icon={<RefreshCw />}
          description={loading ? 'Loading history…' : `${runs.length} recent ${runs.length === 1 ? 'run' : 'runs'}`}
        >
          {runs.length === 0 ? (
            <p className="text-muted-foreground">No sleep history is available yet.</p>
          ) : (
            <ul className="-mx-2 flex flex-col gap-0.5">
              {runs.map((run, index) => (
                <li key={run.id || `${run.startedAt || 'run'}-${index}`}>
                  <Button
                    variant={selectedRunId === run.id ? 'secondary' : 'ghost'}
                    className="h-auto w-full justify-start gap-3 py-2 text-left"
                    aria-pressed={selectedRunId === run.id}
                    onClick={() => selectRun(run)}
                  >
                    <span className="flex w-28 shrink-0 flex-col">
                      <span>{formatSleepTimestamp(run.startedAt)}</span>
                      <span className="font-mono font-normal text-muted-foreground">{titleCase(run.trigger)}</span>
                    </span>
                    <span className="min-w-0 flex-1 truncate font-normal text-muted-foreground">{runSummary(run)}</span>
                    <StatusPill status={run.status} />
                    <ChevronRight data-icon="inline-end" />
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      {selectedRun && (
        <Panel
          title="Changed memories"
          icon={<Archive />}
          description="Inspect the compact delta returned for this run."
          contentClassName="flex flex-col gap-3"
        >
          <ToggleGroup
            variant="outline"
            size="sm"
            spacing={0}
            className="max-w-full overflow-x-auto"
            value={[changeFilter]}
            onValueChange={(next) => next[0] && setChangeFilter(next[0] as ChangeFilter)}
            aria-label="Memory change filters"
          >
            {FILTERS.map((filter) => (
              <ToggleGroupItem key={filter.value} value={filter.value}>
                {filter.label}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
          {selectedRun.changes.length === 0 ? (
            <p className="text-muted-foreground">No per-memory change details were returned for this run.</p>
          ) : filteredChanges.length === 0 ? (
            <p className="text-muted-foreground">No {changeFilter} memories were returned for this run.</p>
          ) : (
            <ul className="grid gap-x-8 md:grid-cols-2">
              {filteredChanges.map((change) => <ChangeRow key={change.id} change={change} />)}
            </ul>
          )}
        </Panel>
      )}
    </section>
  );
}

function StatusPill({ status }: { status: SleepStatus }) {
  const active = isActiveStatus(status);
  return (
    <Badge
      variant={status === 'failed' ? 'destructive' : 'outline'}
      className={status === 'completed' ? 'text-signal' : undefined}
    >
      {active && <Spinner data-icon="inline-start" />}
      {!active && status === 'completed' && <CheckCircle2 data-icon="inline-start" />}
      {!active && status === 'failed' && <AlertTriangle data-icon="inline-start" />}
      {active ? 'Running…' : formatSleepStatus(status)}
    </Badge>
  );
}

function Delta({ before, after }: { before?: number; after?: number }) {
  if (before === undefined || after === undefined || before === after) {
    return <span className="font-mono text-faint">—</span>;
  }
  const increase = after > before;
  return (
    <span className="inline-flex items-center gap-1 font-mono tabular-nums">
      {increase ? <TrendingUp className="size-3" aria-hidden="true" /> : <TrendingDown className="size-3" aria-hidden="true" />}
      <Num
        value={after - before}
        format={{ signDisplay: 'always', maximumFractionDigits: Number.isInteger(after - before) ? 0 : 2 }}
      />
    </span>
  );
}

function ChangeRow({ change }: { change: MemoryChange }) {
  const Icon = change.kind === 'reinforced' ? TrendingUp : change.kind === 'weakened' ? TrendingDown : change.kind === 'unchanged' ? Check : Archive;
  return (
    <li className="flex gap-3 border-b py-2.5">
      <Icon className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
      <div className="flex min-w-0 flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <Eyebrow>{titleCase(change.kind)}</Eyebrow>
          {change.afterStatus && <Badge variant="outline" className="font-mono">{change.afterStatus}</Badge>}
        </div>
        <span className="font-medium text-pretty">{change.title}</span>
        {(change.beforeScore !== undefined || change.afterScore !== undefined) && (
          <span className="font-mono text-muted-foreground">
            Retention: {formatMetric(change.beforeScore, 'score')} → {formatMetric(change.afterScore, 'score')}
          </span>
        )}
      </div>
    </li>
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

/** A snapshot value as a rolling number: counts as integers, scores (0–1) to two places. */
function Metric({ value, format = 'count' }: { value?: number; format?: 'count' | 'score' }) {
  if (value === undefined) return <span className="text-faint">—</span>;
  if (format === 'score') {
    return value <= 1 ? <Num value={value} format={SCORE_FORMAT} /> : <Num value={value} format={{ maximumFractionDigits: 1 }} suffix="%" />;
  }
  return <Num value={value} />;
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
