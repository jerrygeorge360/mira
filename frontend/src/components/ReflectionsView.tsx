import { api } from '../api/client';
import { useLiveData, formatTime } from '../api/useLiveData';
import { useApp } from '../context/AppContext';
import { ViewStatus } from './ViewStatus';
import { Eyebrow, ViewHeader, ViewPage } from './view';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardFooter } from '@/components/ui/card';

export default function ReflectionsView() {
  const { memoryRefreshKey } = useApp();
  const { data, status } = useLiveData(() => api.reflections({ limit: 50 }), [memoryRefreshKey]);
  const items = data?.items ?? [];

  return (
    <ViewPage className="max-w-3xl">
      <ViewHeader
        title="Reflections"
        description="Higher-order patterns synthesized from evidence. A reflection is a cross-turn pattern, not a single extracted fact or standing instruction; those belong in their own memory surfaces."
      />
      {items.length === 0 ? (
        <ViewStatus
          status={status}
          emptyLabel="No reflections yet."
          hint="Reflections form once enough related, important observations accumulate."
        />
      ) : (
        <ul className="flex flex-col gap-3">
          {items.map((r, i) => {
            const kind = String(r.reflection_type ?? '').replace(/_/g, ' ');
            const state = String(r.status ?? '');
            return (
              <li key={i}>
                <Card>
                  <CardContent className="flex flex-col gap-2">
                    <Eyebrow>Pattern{kind ? ` · ${kind}` : ''}</Eyebrow>
                    <p className="text-sm leading-relaxed text-pretty">{String(r.content ?? '')}</p>
                  </CardContent>
                  <CardFooter className="gap-2">
                    <span className="font-mono text-xs text-muted-foreground">{formatTime(r.created_at)}</span>
                    {state && state !== 'active' && <Badge variant="secondary">{state}</Badge>}
                  </CardFooter>
                </Card>
              </li>
            );
          })}
        </ul>
      )}
    </ViewPage>
  );
}
