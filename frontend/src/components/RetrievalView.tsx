import { api } from '../api/client';
import { useApp } from '../context/AppContext';
import { useLiveData } from '../api/useLiveData';
import { ViewStatus } from './ViewStatus';

type Row = Record<string, unknown>;

function score(value: unknown): string {
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(2) : '—';
}

export default function RetrievalView() {
  const { lastTraceId } = useApp();
  const { data, status } = useLiveData(
    () => (lastTraceId ? api.retrievalTrace(lastTraceId) : Promise.reject(new Error('no trace'))),
    [lastTraceId],
  );
  const rows = (data?.evidence as Row[] | undefined) ?? [];
  const mode = data?.retrieval_mode ? ` · ${String(data.retrieval_mode)} mode` : '';

  return (
    <div>
      <div className="view-header">
        <h2>Retrieval Trace</h2>
        <p>Evidence retrieved for the last query — ranked by relevance{rows.length ? mode : ''}</p>
      </div>
      {rows.length === 0 ? (
        <ViewStatus
          status={lastTraceId ? status : 'live'}
          emptyLabel={lastTraceId ? 'No evidence retrieved for the last query.' : 'No query yet.'}
          hint={
            lastTraceId
              ? 'This query answered without retrieved memory (e.g. general knowledge).'
              : 'Ask MIRA something in Chat (real backend) to generate a retrieval trace.'
          }
        />
      ) : (
        <div className="retrieval-evidence">
          {rows.map((r, i) => (
            <div key={i} className="evidence-card">
              <div className="evidence-rank">{i + 1}</div>
              <div className="evidence-meta">
                <div className="evidence-title">{String(r.content ?? r.source_id ?? '')}</div>
                <div className="evidence-source">{String(r.source ?? '')}</div>
              </div>
              <div className="evidence-score">{score(r.score)}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
