import { GitMerge, Network, ShieldCheck } from 'lucide-react';
import { api } from '../api/client';
import { useLiveData } from '../api/useLiveData';
import { useApp } from '../context/AppContext';
import { ViewStatus } from './ViewStatus';

type Row = Record<string, unknown>;

export default function CommunitiesView() {
  const { memoryRefreshKey } = useApp();
  const { data, status } = useLiveData(
    () => api.communitySummaries({ limit: 50 }),
    [memoryRefreshKey],
  );
  const items = (data?.items as Row[] | undefined) ?? [];

  return (
    <div>
      <div className="view-header">
        <h2>Communities</h2>
        <p>
          Graph-derived warm retrieval contexts. Overlap is preserved when communities support
          different retrieval angles.
        </p>
      </div>
      {items.length === 0 ? (
        <ViewStatus
          status={status}
          emptyLabel="No communities yet."
          hint="Community summaries are built once the entity graph is dense enough to cluster."
        />
      ) : (
        <div className="communities-grid">
          {items.map((community) => <CommunityCard key={String(community.id)} community={community} />)}
        </div>
      )}
    </div>
  );
}

function CommunityCard({ community }: { community: Row }) {
  const overlaps = asRows(community.overlapping_communities);
  const recommendation = text(community.merge_recommendation, 'preserve_for_context');
  const review = recommendation === 'review_possible_duplicate';
  return (
    <article className={`community-card${review ? ' review' : ''}`}>
      <div className="community-card-top">
        <div>
          <div className="community-kicker">Community · {shortId(text(community.community_id))}</div>
          <h3>{text(community.title, text(community.community_id, 'Community'))}</h3>
        </div>
        <div className={`community-recommendation${review ? ' review' : ''}`}>
          {review ? <GitMerge size={15} /> : <ShieldCheck size={15} />}
          {labelize(recommendation)}
        </div>
      </div>

      <p className="community-summary">{text(community.summary)}</p>

      <div className="community-stats">
        <Stat label="Memories" value={String(number(community.member_count))} />
        <Stat label="Cohesion" value={number(community.cohesion_score).toFixed(2)} />
        <Stat label="Updated" value={formatTime(text(community.updated_at))} />
      </div>

      <div className="community-explanation">
        <Network size={15} />
        <span>{text(community.community_explanation)}</span>
      </div>

      {overlaps.length > 0 ? (
        <div className="community-overlaps">
          <h4>Overlapping communities</h4>
          {overlaps.map((overlap) => (
            <div className="community-overlap-row" key={String(overlap.id)}>
              <strong>{text(overlap.title, text(overlap.community_id, 'Community'))}</strong>
              <span>
                {number(overlap.shared_member_count)} shared · {percent(number(overlap.member_overlap_ratio))} member overlap
              </span>
            </div>
          ))}
        </div>
      ) : (
        <div className="community-overlaps empty">No overlap detected in the current summary set.</div>
      )}

      <details className="community-details">
        <summary>Member node ids</summary>
        <pre>{JSON.stringify(community.member_nodes_json ?? [], null, 2)}</pre>
      </details>
    </article>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="community-stat">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

function asRows(value: unknown): Row[] {
  return Array.isArray(value)
    ? value.filter((item): item is Row => Boolean(item) && typeof item === 'object' && !Array.isArray(item))
    : [];
}

function text(value: unknown, fallback = '') {
  return typeof value === 'string' && value ? value : fallback;
}

function number(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function shortId(value: string) {
  return value ? value.replace(/^community_/, '').slice(0, 12) : 'unknown';
}

function labelize(value: string) {
  return (value || 'unknown').replaceAll('_', ' ');
}

function percent(value: number) {
  return `${Math.round(value * 100)}%`;
}

function formatTime(value: string) {
  if (!value) return 'Unknown';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}
