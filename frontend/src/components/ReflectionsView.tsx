import { api } from '../api/client';
import { useLiveData, formatTime } from '../api/useLiveData';
import { useApp } from '../context/AppContext';
import { ViewStatus } from './ViewStatus';

export default function ReflectionsView() {
  const { memoryRefreshKey } = useApp();
  const { data, status } = useLiveData(() => api.reflections({ limit: 50 }), [memoryRefreshKey]);
  const items = data?.items ?? [];

  return (
    <div>
      <div className="view-header">
        <h2>Reflections</h2>
        <p>Higher-order patterns synthesized from evidence. Facts, deadlines, and preferences belong in their own memory surfaces.</p>
      </div>
      {items.length === 0 ? (
        <ViewStatus
          status={status}
          emptyLabel="No reflections yet."
          hint="Reflections form once enough related, important observations accumulate."
        />
      ) : (
        <div className="reflection-list">
          {items.map((r, i) => {
            const tags = [
              String(r.reflection_type ?? '').replace(/_/g, ' '),
              String(r.status ?? ''),
            ].filter((t) => t && t !== 'active');
            return (
              <div key={i} className="reflection-card">
                <div className="reflection-kind">Pattern · {String(r.reflection_type ?? '').replace(/_/g, ' ')}</div>
                <div className="reflection-insight">{String(r.content ?? '')}</div>
                <div className="reflection-boundary">
                  Reflection means a cross-turn pattern, not a single extracted fact or standing instruction.
                </div>
                <div className="reflection-tags">
                  <span className="chip">{formatTime(r.created_at)}</span>
                  {tags.map((tag, j) => (
                    <span key={j} className="chip chip-accent">
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
