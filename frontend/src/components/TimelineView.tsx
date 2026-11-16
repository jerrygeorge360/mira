import { useState } from 'react';
import { api } from '../api/client';
import { useLiveData, formatTime } from '../api/useLiveData';
import { useApp } from '../context/AppContext';
import { ViewStatus } from './ViewStatus';

type Row = Record<string, unknown>;

export default function TimelineView() {
  const { memoryRefreshKey } = useApp();
  const { data, status, setData } = useLiveData(async () => {
    const [active, pending, candidates] = await Promise.all([
      api.foresight({ limit: 50 }),
      api.foresight({ status: 'pending', limit: 50 }),
      api.foresight({ status: 'candidate', limit: 50 }),
    ]);
    return { items: [...active.items, ...pending.items, ...candidates.items] };
  }, [memoryRefreshKey]);
  const [confirmingId, setConfirmingId] = useState('');
  const [actionMessage, setActionMessage] = useState('');
  const [actionError, setActionError] = useState('');
  const rows = (data?.items as Row[] | undefined) ?? [];

  async function confirmCandidate(row: Row) {
    const id = String(row.id ?? '');
    if (!id) return;
    setConfirmingId(id);
    setActionMessage('');
    setActionError('');
    try {
      await api.confirmForesightCandidate(id);
      setData(current => current ? {
        ...current,
        items: current.items.map(item => item.id === id ? { ...item, status: 'pending' } : item),
      } : current);
      setActionMessage('Confirmed. This reminder is active for this workspace until its event date.');
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Could not confirm this reminder.');
    } finally {
      setConfirmingId('');
    }
  }

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
          <div className="timeline-group-label">Upcoming</div>
          {actionMessage ? <div className="timeline-action-message">{actionMessage}</div> : null}
          {actionError ? <div className="timeline-action-error" role="alert">{actionError}</div> : null}
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
                {t.status === 'candidate' ? (
                  <div className="timeline-candidate-action">
                    <p>Suggested from a document. Confirm only if this date applies to your workspace.</p>
                    <button
                      className="btn-primary timeline-confirm-button"
                      type="button"
                      onClick={() => void confirmCandidate(t)}
                      disabled={confirmingId === String(t.id ?? '')}
                    >
                      {confirmingId === String(t.id ?? '') ? 'Confirming…' : 'Confirm reminder'}
                    </button>
                  </div>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
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
