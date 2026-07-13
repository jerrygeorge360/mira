import { api } from '../api/client';
import { useLiveData } from '../api/useLiveData';
import { ViewStatus } from './ViewStatus';

export default function CommunitiesView() {
  const { data, status } = useLiveData(() => api.communitySummaries({ limit: 50 }), []);
  const items = data?.items ?? [];

  return (
    <div>
      <div className="view-header">
        <h2>Communities</h2>
        <p>Leiden-detected clusters from the temporal memory graph</p>
      </div>
      {items.length === 0 ? (
        <ViewStatus
          status={status}
          emptyLabel="No communities yet."
          hint="Community summaries are built once the entity graph is dense enough to cluster."
        />
      ) : (
        <div className="communities-grid">
          {items.map((c, i) => {
            const members = Array.isArray(c.member_nodes_json) ? c.member_nodes_json.length : 0;
            return (
              <div key={i} className="community-card">
                <div className="community-title">
                  {String(c.title ?? c.community_id ?? 'Community')}
                </div>
                <div className="community-stats">
                  <div className="community-stat">
                    <strong>{members}</strong>
                    <span>Entities</span>
                  </div>
                </div>
                {c.summary ? <div className="community-delta">{String(c.summary)}</div> : null}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
