import { Activity, Archive, Clock3, Flame, Info, Layers3, MoveRight, ShieldCheck } from 'lucide-react';
import { api } from '../api/client';
import { formatTime, useLiveData } from '../api/useLiveData';

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
  const { data, status } = useLiveData(() => api.memoryHealth(), []);
  const health = asRecord(data?.health);
  const tiers = asRecord(health.tiers);
  const workingSet = asRecord(health.working_set);
  const retention = asRecord(health.retention);
  const instrumentation = asRecord(health.instrumentation);
  const movements = asArray(health.recent_movements).map(toMovement);

  if (status === 'loading') {
    return <div className="view-empty"><div className="view-empty-msg">Loading memory health...</div></div>;
  }
  if (status === 'offline') {
    return (
      <div className="view-empty">
        <div className="view-empty-msg">Backend offline</div>
        <div className="view-empty-hint">Start the API to inspect memory health.</div>
      </div>
    );
  }

  const tierCards = [
    { key: 'hot', icon: <Flame size={18} />, tone: 'hot', tier: toTier(tiers.hot) },
    { key: 'warm', icon: <Activity size={18} />, tone: 'warm', tier: toTier(tiers.warm) },
    { key: 'cold', icon: <Archive size={18} />, tone: 'cold', tier: toTier(tiers.cold) },
    { key: 'time_bound', icon: <Clock3 size={18} />, tone: 'time', tier: toTier(tiers.time_bound) },
  ];

  return (
    <div>
      <div className="view-header">
        <h2>Memory Health</h2>
        <p>What is hot, what is durable, and which records have left active use.</p>
      </div>

      <div className="health-tier-grid">
        {tierCards.map(({ key, icon, tone, tier }) => (
          <section key={key} className={`health-tier-card ${tone}`}>
            <div className="health-tier-top">
              <div className="health-tier-icon">{icon}</div>
              <div>
                <h3>{tier.label}</h3>
                <p>{tier.description || 'Persisted memory state.'}</p>
              </div>
              <strong>{tier.count}</strong>
            </div>
            {typeof tier.capacity === 'number' && (
              <div className="health-pressure">
                <div className="health-pressure-row">
                  <span>Capacity</span>
                  <strong>{Math.round((tier.pressure ?? 0) * 100)}% · {tier.count}/{tier.capacity}</strong>
                </div>
                <div className="health-pressure-track">
                  <div style={{ width: `${Math.min(100, Math.round((tier.pressure ?? 0) * 100))}%` }} />
                </div>
              </div>
            )}
            <KeyValueList title="Components" values={tier.components} />
            <KeyValueList title="Statuses" values={tier.statuses} />
          </section>
        ))}
      </div>

      <div className="health-panels">
        <section className="health-panel">
          <div className="health-panel-title">
            <Layers3 size={17} />
            <h3>Session Working Set</h3>
          </div>
          <div className="health-status-line">
            <span>Active</span>
            <strong>{numberFrom(workingSet.active_count)}</strong>
          </div>
          <div className="health-status-line">
            <span>Terminal</span>
            <strong>{numberFrom(workingSet.terminal_count)}</strong>
          </div>
          <KeyValueList title="Statuses" values={asRecord(workingSet.statuses)} />
          <p className="health-note">{String(workingSet.pressure_note || '')}</p>
        </section>

        <section className="health-panel">
          <div className="health-panel-title">
            <ShieldCheck size={17} />
            <h3>Retention Signals</h3>
          </div>
          <KeyValueList values={asRecord(retention.forgetting_signals)} />
        </section>
      </div>

      <section className="health-section">
        <div className="health-section-head">
          <MoveRight size={17} />
          <h3>Recent status changes</h3>
        </div>
        {movements.length === 0 ? (
          <div className="view-empty compact">
            <div className="view-empty-msg">No inactive memory records yet</div>
            <div className="view-empty-hint">Demotions, expirations, supersessions, and resolved records appear here.</div>
          </div>
        ) : (
          <div className="health-movement-list">
            {movements.map((movement) => (
              <article key={`${movement.source}-${movement.id}`} className="health-movement-card">
                <div className="health-movement-main">
                  <div>
                    <span>{movement.source.replaceAll('_', ' ')}</span>
                    <h4>{movement.title}</h4>
                  </div>
                  <strong>{formatTime(movement.updated_at)}</strong>
                </div>
                <div className="health-movement-route">
                  <b>{movement.from}</b>
                  <MoveRight size={14} />
                  <b>{movement.to}</b>
                </div>
                <p>{movement.reason}</p>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="health-section">
        <div className="health-section-head">
          <Info size={17} />
          <h3>Instrumentation boundary</h3>
        </div>
        <div className="health-boundary-grid">
          <BoundaryList title="Persisted today" items={asStringArray(instrumentation.persisted)} />
          <BoundaryList title="Not persisted yet" items={asStringArray(instrumentation.not_persisted_yet)} muted />
        </div>
      </section>
    </div>
  );
}

function KeyValueList({ title, values }: { title?: string; values?: JsonRecord }) {
  const entries = Object.entries(values ?? {}).filter(([, value]) => value !== null && value !== undefined);
  if (entries.length === 0) return null;
  return (
    <div className="health-kv">
      {title && <h4>{title}</h4>}
      {entries.map(([key, value]) => (
        <div key={key}>
          <span>{key.replaceAll('_', ' ')}</span>
          <strong>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</strong>
        </div>
      ))}
    </div>
  );
}

function BoundaryList({ title, items, muted = false }: { title: string; items: string[]; muted?: boolean }) {
  return (
    <div className={`health-boundary-card${muted ? ' muted' : ''}`}>
      <h4>{title}</h4>
      <ul>
        {items.map((item) => <li key={item}>{item}</li>)}
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
