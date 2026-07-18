import { Activity, Boxes, Cable, Clock3, ShieldCheck, Users } from 'lucide-react';
import { api } from '../api/client';
import { formatTime, useLiveData } from '../api/useLiveData';

export default function AdminView() {
  const { data, status } = useLiveData(() => api.adminOverview(), []);

  if (status === 'loading') {
    return <div className="view-empty"><div className="view-empty-msg">Loading platform overview...</div></div>;
  }
  if (status === 'offline' || !data) {
    return (
      <div className="view-empty">
        <div className="view-empty-msg">Administration unavailable</div>
        <div className="view-empty-hint">This view requires an explicitly configured platform administrator.</div>
      </div>
    );
  }

  const workspaceTotal = sumValues(data.workspaces);
  const queueTotal = sumValues(data.queue);
  const queueAttention = (data.queue.failed ?? 0)
    + (data.queue.dead_letter ?? 0)
    + (data.queue.quarantined ?? 0);
  const maxRegistrations = Math.max(1, ...data.registrations_last_30_days.map(item => item.count));

  return (
    <div className="admin-view">
      <div className="view-header admin-view-header">
        <div>
          <h2>Administration</h2>
          <p>Aggregate product usage and runtime health. No conversation or memory content is exposed.</p>
        </div>
        <span><ShieldCheck size={14} /> Read only</span>
      </div>

      <div className="admin-metric-grid">
        <Metric icon={<Users size={18} />} label="Registered people" value={data.users.registered} detail={`${data.users.new_last_7_days} joined in 7 days`} />
        <Metric icon={<Activity size={18} />} label="Active people" value={data.users.active_last_7_days} detail="Logged in during the last 7 days" />
        <Metric icon={<Boxes size={18} />} label="Active workspaces" value={workspaceTotal} detail={`${data.workspaces.personal ?? 0} personal · ${data.workspaces.demo ?? 0} demo`} />
        <Metric icon={<Clock3 size={18} />} label="Active sessions" value={data.activity.active_web_sessions} detail={`${data.activity.conversations} conversations`} />
      </div>

      <div className="admin-panel-grid">
        <section className="admin-panel">
          <div className="admin-panel-title"><Users size={17} /><h3>Registration</h3></div>
          <div className="admin-kv"><span>Last 7 days</span><strong>{data.users.new_last_7_days}</strong></div>
          <div className="admin-kv"><span>Last 30 days</span><strong>{data.users.new_last_30_days}</strong></div>
          <div className="admin-kv"><span>Active in 7 days</span><strong>{data.users.active_last_7_days}</strong></div>
          <div className="admin-registration-list">
            {data.registrations_last_30_days.length === 0 ? (
              <p>No registrations in the last 30 days.</p>
            ) : data.registrations_last_30_days.map(item => (
              <div key={item.date}>
                <time dateTime={item.date}>{formatDate(item.date)}</time>
                <span><i style={{ width: `${Math.max(8, (item.count / maxRegistrations) * 100)}%` }} /></span>
                <strong>{item.count}</strong>
              </div>
            ))}
          </div>
        </section>

        <section className="admin-panel">
          <div className="admin-panel-title"><Activity size={17} /><h3>Runtime activity</h3></div>
          <div className="admin-kv"><span>Conversations</span><strong>{data.activity.conversations}</strong></div>
          <div className="admin-kv"><span>Observations</span><strong>{data.activity.observations}</strong></div>
          <div className="admin-kv"><span>Retrieval traces</span><strong>{data.activity.retrieval_traces}</strong></div>
          <div className="admin-kv"><span>Queue records</span><strong>{queueTotal}</strong></div>
          <div className={`admin-status${queueAttention > 0 ? ' attention' : ''}`}>
            <span>{queueAttention > 0 ? 'Queue needs attention' : 'No queue failures'}</span>
            <strong>{queueAttention}</strong>
          </div>
        </section>

        <section className="admin-panel">
          <div className="admin-panel-title"><Cable size={17} /><h3>OAuth and MCP</h3></div>
          <div className="admin-kv"><span>Registered clients</span><strong>{data.oauth.registered_clients}</strong></div>
          <div className="admin-kv"><span>Active access tokens</span><strong>{data.oauth.active_access_tokens}</strong></div>
          <div className="admin-kv"><span>Pending work</span><strong>{data.queue.pending ?? 0}</strong></div>
          <div className="admin-kv"><span>Quarantined work</span><strong>{data.queue.quarantined ?? 0}</strong></div>
        </section>

        <section className="admin-panel">
          <div className="admin-panel-title"><Boxes size={17} /><h3>Workspace distribution</h3></div>
          {Object.entries(data.workspaces).map(([type, count]) => (
            <div className="admin-kv" key={type}>
              <span>{type.replaceAll('_', ' ')}</span>
              <strong>{count}</strong>
            </div>
          ))}
          <p className="admin-generated">Snapshot generated {formatTime(data.generated_at)}</p>
        </section>
      </div>
    </div>
  );
}

function Metric({ icon, label, value, detail }: { icon: React.ReactNode; label: string; value: number; detail: string }) {
  return (
    <section className="admin-metric">
      <div>{icon}</div>
      <span>{label}</span>
      <strong>{value.toLocaleString()}</strong>
      <p>{detail}</p>
    </section>
  );
}

function sumValues(values: Record<string, number>): number {
  return Object.values(values).reduce((total, value) => total + value, 0);
}

function formatDate(value: string): string {
  const date = new Date(`${value}T00:00:00Z`);
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
}
