import { api } from '../api/client';
import { useLiveData, formatTime } from '../api/useLiveData';
import { ViewStatus } from './ViewStatus';

type Row = Record<string, unknown>;

export default function TimelineView() {
  const { data, status } = useLiveData(() => api.foresight({ limit: 50 }), []);
  const rows = (data?.items as Row[] | undefined) ?? [];

  return (
    <div>
      <div className="view-header">
        <h2>Foresight Timeline</h2>
        <p>Future-relevant anchor points surfaced from session observations</p>
      </div>
      {rows.length === 0 ? (
        <ViewStatus
          status={status}
          emptyLabel="No foresight records yet."
          hint="Time-sensitive commitments (deadlines, upcoming events) surface here as you talk to MIRA."
        />
      ) : (
        <div className="timeline">
          <div className="timeline-group-label">Upcoming</div>
          {rows.map((t, i) => (
            <div key={i} className="timeline-item">
              <div className="timeline-dot" />
              <div className="timeline-item-text">
                <div className="timeline-item-title">{String(t.content ?? '')}</div>
                <div className="timeline-item-kind">
                  {t.created_at ? `Foresight · ${formatTime(t.created_at)}` : 'Foresight'}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
