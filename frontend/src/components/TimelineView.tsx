import { api } from '../api/client';
import { useLiveData, formatTime } from '../api/useLiveData';
import { useApp } from '../context/AppContext';
import { ViewStatus } from './ViewStatus';
import { ViewHeader, ViewPage } from './view';
import { Badge } from '@/components/ui/badge';

type Row = Record<string, unknown>;

export default function TimelineView() {
  const { memoryRefreshKey } = useApp();
  const { data, status } = useLiveData(() => api.foresight({ limit: 50 }), [memoryRefreshKey]);
  const rows = (data?.items as Row[] | undefined) ?? [];

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
              </li>
            );
          })}
        </ol>
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
