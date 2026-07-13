import { api } from '../api/client';
import { useLiveData, formatTime } from '../api/useLiveData';
import { ViewStatus } from './ViewStatus';

export default function ReflectionsView() {
  const { data, status } = useLiveData(() => api.reflections({ limit: 50 }), []);
  const items = data?.items ?? [];

  return (
    <div>
      <div className="view-header">
        <h2>Reflections</h2>
        <p>Gated higher-order patterns synthesized from accumulated evidence</p>
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
                <div className="reflection-time">{formatTime(r.created_at)}</div>
                <div className="reflection-insight">{String(r.content ?? '')}</div>
                <div className="reflection-tags">
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
