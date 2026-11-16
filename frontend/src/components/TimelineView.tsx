import { useState } from 'react';
import { api } from '../api/client';
import { useLiveData, formatTime } from '../api/useLiveData';
import { useApp } from '../context/AppContext';
import { ViewStatus } from './ViewStatus';
import { ViewHeader, ViewPage } from './view';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

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
    <ViewPage className="max-w-3xl">
      <ViewHeader
        title="Foresight"
        description="Future-relevant checks, deadlines, and validity windows. Standing preferences stay in Working Set."
      />
      {rows.length === 0 ? (
        <ViewStatus
          status={status}
          emptyLabel="No foresight records yet."
          hint="Time-sensitive commitments (deadlines, upcoming events) surface here as you talk to MIRA."
        />
      ) : (
        // a rail on the left carries the timeline; each record hangs off it by a node
        <>
        {actionMessage && <p role="status" className="mb-3 rounded-md border border-signal/30 bg-signal/5 px-3 py-2 text-xs text-signal">{actionMessage}</p>}
        {actionError && <p role="alert" className="mb-3 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">{actionError}</p>}
        <ol className="ml-1.5 flex flex-col border-l">
          {rows.map((t, i) => {
            const state = String(t.status ?? 'pending');
            return (
              <li key={i} className="relative flex flex-col gap-1.5 py-4 pl-6">
                <span
                  className="absolute top-5.5 -left-[4.5px] size-2 rounded-full border border-signal bg-background data-[state=pending]:bg-signal"
                  data-state={state}
                  aria-hidden="true"
                />
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={state === 'pending' ? 'outline' : 'secondary'} className="font-mono">
                    {state}
                  </Badge>
                  <span className="font-mono text-xs text-muted-foreground">{timelineMeta(t)}</span>
                </div>
                <p className="text-sm font-medium text-pretty">{String(t.content ?? '')}</p>
                {t.reason ? <p className="text-xs text-pretty text-muted-foreground">{String(t.reason)}</p> : null}
                {state === 'candidate' ? (
                  <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border p-3">
                    <p className="text-xs text-muted-foreground">Suggested from a document. Confirm only if this date applies to your workspace.</p>
                    <Button size="sm" onClick={() => void confirmCandidate(t)} disabled={confirmingId === String(t.id ?? '')}>
                      {confirmingId === String(t.id ?? '') ? 'Confirming…' : 'Confirm reminder'}
                    </Button>
                  </div>
                ) : null}
              </li>
            );
          })}
        </ol>
        </>
      )}
    </ViewPage>
  );
}

function timelineMeta(row: Row) {
  const parts: string[] = [];
  if (row.valid_from) parts.push(`from ${formatTime(row.valid_from)}`);
  if (row.valid_until) parts.push(`until ${formatTime(row.valid_until)}`);
  if (!row.valid_from && !row.valid_until && row.created_at) {
    parts.push(`created ${formatTime(row.created_at)}`);
  }
  return parts.join(' · ');
}
