import { Activity, Archive, Clock3, Flame, Info, Layers3, MoveRight, ShieldCheck } from 'lucide-react';
import { api } from '../api/client';
import { formatTime, useLiveData } from '../api/useLiveData';
import { useApp } from '../context/AppContext';
import MemorySleepPanel from './MemorySleepPanel';
import LoadingState from './LoadingState';
import HealthInsights from './HealthInsights';
import { Eyebrow, KeyValue, KeyValueList, Num, Panel, ViewHeader, ViewPage } from './view';
import { Badge } from '@/components/ui/badge';
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import { Progress } from '@/components/ui/progress';

type JsonRecord = Record<string, unknown>;

interface Tier {
  label: string;
  count: number;
  capacity?: number;
  pressure?: number;
  description?: string;
  statuses?: JsonRecord;
  components?: JsonRecord;
}

interface Movement {
  source: string;
  id: string;
  title: string;
  from: string;
  to: string;
  reason: string;
  updated_at?: string;
}

export default function MemoryHealthView() {
  const { memoryRefreshKey } = useApp();
  const { data, status } = useLiveData(() => api.memoryHealth(), [memoryRefreshKey]);
  const health = asRecord(data?.health);
  const tiers = asRecord(health.tiers);
  const workingSet = asRecord(health.working_set);
  const retention = asRecord(health.retention);
  const instrumentation = asRecord(health.instrumentation);
  const movements = asArray(health.recent_movements).map(toMovement);

  if (status === 'loading') {
    return (
      <Empty className="border">
        <LoadingState label="Loading memory health" />
      </Empty>
    );
  }
  if (status === 'offline') {
    return (
      <Empty className="border">
        <EmptyHeader>
          <EmptyTitle>Backend offline</EmptyTitle>
          <EmptyDescription>Start the API to inspect memory health.</EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  const tierCards = [
    { key: 'hot', icon: <Flame />, tier: toTier(tiers.hot) },
    { key: 'warm', icon: <Activity />, tier: toTier(tiers.warm) },
    { key: 'cold', icon: <Archive />, tier: toTier(tiers.cold) },
    { key: 'time_bound', icon: <Clock3 />, tier: toTier(tiers.time_bound) },
  ];
  const pressureNote = String(workingSet.pressure_note || '');

  return (
    <ViewPage>
      <ViewHeader
        title="Memory Health"
        description="What is hot, what is durable, and which records have left active use."
      />

      <HealthInsights
        tiers={tierCards.map(({ key, tier }) => ({
          key,
          label: tier.label,
          count: tier.count,
          description: tier.description,
          capacity: tier.capacity,
          pressure: tier.pressure,
        }))}
      />

      <div className="grid items-start gap-4 md:grid-cols-2">
        {tierCards.map(({ key, icon, tier }) => {
          const percent = Math.round((tier.pressure ?? 0) * 100);
          return (
            <Panel
              key={key}
              title={tier.label}
              icon={icon}
              description={tier.description || 'Persisted memory state.'}
              action={<span className="font-mono text-2xl font-medium"><Num value={tier.count} /></span>}
              contentClassName="flex flex-col gap-4"
            >
              {typeof tier.capacity === 'number' && (
                <div className="flex flex-col gap-1.5">
                  <div className="flex items-baseline justify-between gap-3">
                    <Eyebrow>Capacity</Eyebrow>
                    <span className="font-mono text-xs tabular-nums">
                      <Num value={percent} suffix="%" /> · <Num value={tier.count} />/{tier.capacity}
                    </span>
                  </div>
                  <Progress value={Math.min(100, percent)} aria-label={`${tier.label} capacity used`} />
                </div>
              )}
              <RecordList title="Components" values={tier.components} />
              <RecordList title="Statuses" values={tier.statuses} />
            </Panel>
          );
        })}
      </div>

      <div className="grid items-start gap-4 md:grid-cols-2">
        <Panel title="Session Working Set" icon={<Layers3 />} contentClassName="flex flex-col gap-4">
          <KeyValueList>
            <KeyValue label="Active">{numberFrom(workingSet.active_count)}</KeyValue>
            <KeyValue label="Terminal">{numberFrom(workingSet.terminal_count)}</KeyValue>
          </KeyValueList>
          <RecordList title="Statuses" values={asRecord(workingSet.statuses)} />
          {pressureNote && <p className="text-xs text-pretty text-muted-foreground">{pressureNote}</p>}
        </Panel>

        <Panel title="Retention Signals" icon={<ShieldCheck />}>
          <RecordList values={asRecord(retention.forgetting_signals)} empty="No retention signals recorded." />
        </Panel>
      </div>

      <MemorySleepPanel />

      <Panel title="Recent status changes" icon={<MoveRight />}>
        {movements.length === 0 ? (
          <Empty>
            <EmptyHeader>
              <EmptyTitle>No inactive memory records yet</EmptyTitle>
              <EmptyDescription>Demotions, expirations, supersessions, and resolved records appear here.</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <ul className="flex flex-col *:border-b *:last:border-b-0">
            {movements.map((movement) => (
              <li key={`${movement.source}-${movement.id}`} className="flex flex-col gap-1.5 py-3 first:pt-0 last:pb-0">
                <div className="flex items-baseline justify-between gap-4">
                  <Eyebrow>{movement.source.replaceAll('_', ' ')}</Eyebrow>
                  <span className="font-mono text-xs text-muted-foreground">{formatTime(movement.updated_at)}</span>
                </div>
                <h4 className="text-sm font-medium text-pretty">{movement.title}</h4>
                <div className="flex items-center gap-2">
                  <Badge variant="outline" className="font-mono">{movement.from}</Badge>
                  <MoveRight className="size-3.5 text-muted-foreground" aria-hidden="true" />
                  <Badge variant="secondary" className="font-mono">{movement.to}</Badge>
                </div>
                <p className="text-xs text-pretty text-muted-foreground">{movement.reason}</p>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel title="Instrumentation boundary" icon={<Info />}>
        <div className="grid gap-x-8 gap-y-4 md:grid-cols-2">
          <BoundaryList title="Persisted today" items={asStringArray(instrumentation.persisted)} />
          <BoundaryList title="Not persisted yet" items={asStringArray(instrumentation.not_persisted_yet)} muted />
        </div>
      </Panel>
    </ViewPage>
  );
}

/** A record of unknown keys, rendered as label → value rows. */
function RecordList({ title, values, empty }: { title?: string; values?: JsonRecord; empty?: string }) {
  const entries = Object.entries(values ?? {}).filter(([, value]) => value !== null && value !== undefined);
  if (entries.length === 0) return empty ? <p className="text-xs text-muted-foreground">{empty}</p> : null;
  return (
    <div className="flex flex-col gap-1">
      {title && <Eyebrow>{title}</Eyebrow>}
      <KeyValueList>
        {entries.map(([key, value]) => (
          <KeyValue key={key} label={key.replaceAll('_', ' ')}>
            {typeof value === 'number' ? value : typeof value === 'object' ? JSON.stringify(value) : String(value)}
          </KeyValue>
        ))}
      </KeyValueList>
    </div>
  );
}

function BoundaryList({ title, items, muted = false }: { title: string; items: string[]; muted?: boolean }) {
  return (
    <div className="flex flex-col gap-2">
      <Eyebrow>{title}</Eyebrow>
      <ul className={`flex flex-col gap-1.5 text-xs ${muted ? 'text-muted-foreground' : ''}`}>
        {items.map((item) => (
          <li key={item} className="flex gap-2 text-pretty">
            <span className={muted ? 'text-faint' : 'text-signal'} aria-hidden="true">
              {muted ? '○' : '●'}
            </span>
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

function toTier(value: unknown): Tier {
  const record = asRecord(value);
  return {
    label: String(record.label || 'Memory tier'),
    count: numberFrom(record.count),
    capacity: optionalNumber(record.capacity),
    pressure: optionalNumber(record.pressure),
    description: optionalString(record.description),
    statuses: asRecord(record.statuses),
    components: asRecord(record.components),
  };
}

function toMovement(value: unknown): Movement {
  const record = asRecord(value);
  return {
    source: String(record.source || 'memory'),
    id: String(record.id || crypto.randomUUID()),
    title: String(record.title || 'Untitled memory'),
    from: String(record.from || 'active'),
    to: String(record.to || 'inactive'),
    reason: String(record.reason || 'Stored status changed.'),
    updated_at: optionalString(record.updated_at),
  };
}

function asRecord(value: unknown): JsonRecord {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as JsonRecord : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function asStringArray(value: unknown): string[] {
  return asArray(value).map(String);
}

function numberFrom(value: unknown): number {
  return typeof value === 'number' ? value : Number(value || 0);
}

function optionalNumber(value: unknown): number | undefined {
  return value === null || value === undefined ? undefined : numberFrom(value);
}

function optionalString(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined;
}
