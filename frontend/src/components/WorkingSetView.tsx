import { api } from '../api/client';
import { useApp } from '../context/AppContext';
import { useLiveData } from '../api/useLiveData';
import { ViewStatus } from './ViewStatus';

type Row = Record<string, unknown>;

export default function WorkingSetView() {
  const { sessionId } = useApp();
  const { data, status } = useLiveData(
    () => (sessionId ? api.sessionWorkingSet(sessionId) : Promise.reject(new Error('no session'))),
    [sessionId],
  );
  const rows = (data?.items as Row[] | undefined) ?? [];

  return (
    <div>
      <div className="view-header">
        <h2>Session Working Set</h2>
        <p>Active constraints, corrections, and decisions that shape the current response</p>
      </div>
      {rows.length === 0 ? (
        <ViewStatus
          status={sessionId ? status : 'live'}
          emptyLabel={sessionId ? 'No active session items.' : 'No live session yet.'}
          hint={
            sessionId
              ? 'Corrections, constraints, and decisions appear here as you talk to MIRA.'
              : 'Send a message in Chat (real backend) to start a session.'
          }
        />
      ) : (
        <div className="item-list">
          {rows.map((item, i) => {
            const priority = Number(item.priority ?? 0) >= 0.66 ? 'High' : 'Med';
            return (
              <div key={i} className="item-card">
                <div
                  style={{
                    width: 6,
                    height: 6,
                    borderRadius: '50%',
                    background: 'var(--accent)',
                    marginTop: 6,
                    flexShrink: 0,
                  }}
                />
                <div className="item-card-meta">
                  <div className="item-card-title">{String(item.content ?? '')}</div>
                  <div className="item-card-sub">{String(item.scope ?? '')}</div>
                </div>
                <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
                  <span className={`chip ${priority === 'High' ? 'chip-high' : 'chip-med'}`}>
                    {priority}
                  </span>
                  <span className="chip chip-accent">
                    {String(item.type ?? '').replace(/_/g, ' ')}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
