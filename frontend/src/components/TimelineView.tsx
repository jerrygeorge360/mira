import { api } from '../api/client';
import { useLiveData, formatTime } from '../api/useLiveData';
import { useApp } from '../context/AppContext';
import { ViewStatus } from './ViewStatus';

type Row = Record<string, unknown>;

export default function TimelineView() {
  const { memoryRefreshKey } = useApp();
  const { data, status } = useLiveData(() => api.foresight({ status: 'all', limit: 50 }), [memoryRefreshKey]);
  const rows = (data?.items as Row[] | undefined) ?? [];
  const currentRows = rows.filter(row => ['pending', 'active'].includes(String(row.status)));
  const historyRows = rows.filter(row => !['pending', 'active'].includes(String(row.status)));

  return (
    <div>
      <div className="view-header">
        <h2>Foresight</h2>
        <p>Future-relevant checks, deadlines, and validity windows. Standing preferences stay in Working Set.</p>
      </div>
      {rows.length === 0 ? (
        <ViewStatus
          status={status}
          emptyLabel="No foresight records yet."
          hint="Time-sensitive commitments (deadlines, upcoming events) surface here as you talk to MIRA."
        />
      ) : (
        <div className="timeline">
          {currentRows.length > 0 ? <TimelineGroup label="Current" rows={currentRows} /> : null}
          {historyRows.length > 0 ? <TimelineGroup label="History" rows={historyRows} /> : null}
        </div>
      )}
    </div>
  );
}

function TimelineGroup({ label, rows }: { label: string; rows: Row[] }) {
  return (
    <>
      <div className="timeline-group-label">{label}</div>
      {rows.map((t, i) => (
            <div key={i} className="timeline-item">
              <div className="timeline-dot" />
              <div className="timeline-item-text">
                <div className="timeline-item-label">Future trigger · {String(t.status ?? 'pending')}</div>
                <div className="timeline-item-title">{String(t.content ?? '')}</div>
                <div className="timeline-item-kind">
                  {timelineMeta(t)}
                </div>
                {t.reason ? <div className="timeline-item-reason">{String(t.reason)}</div> : null}
              </div>
            </div>
      ))}
    </>
  );
}

function timelineMeta(row: Row) {
  const parts = ['Foresight'];
  if (row.valid_from) parts.push(`from ${formatTime(row.valid_from)}`);
  if (row.valid_until) parts.push(`until ${formatTime(row.valid_until)}`);
  if (!row.valid_from && !row.valid_until && row.created_at) {
    parts.push(`created ${formatTime(row.created_at)}`);
  }
  return parts.join(' · ');
}
