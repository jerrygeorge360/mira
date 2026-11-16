import { GitMerge, ShieldCheck } from 'lucide-react';
import { api } from '../api/client';
import { useLiveData } from '../api/useLiveData';
import { useApp } from '../context/AppContext';
import { ViewStatus } from './ViewStatus';
import { Eyebrow, KeyValue, KeyValueList, ViewHeader, ViewPage } from './view';
import { Badge } from '@/components/ui/badge';
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';

type Row = Record<string, unknown>;

export default function CommunitiesView() {
  const { memoryRefreshKey } = useApp();
  const { data, status } = useLiveData(
    () => api.communitySummaries({ limit: 50 }),
    [memoryRefreshKey],
  );
  const items = (data?.items as Row[] | undefined) ?? [];

  return (
    <ViewPage>
      <ViewHeader
        title="Communities"
        description="Graph-derived warm retrieval contexts. Overlap is preserved when communities support different retrieval angles."
      />
      {items.length === 0 ? (
        <ViewStatus
          status={status}
          emptyLabel="No communities yet."
          hint="Community summaries are built once the entity graph is dense enough to cluster."
        />
      ) : (
        <div className="grid items-start gap-4 lg:grid-cols-2">
          {items.map((community) => <CommunityCard key={String(community.id)} community={community} />)}
        </div>
      )}
    </ViewPage>
  );
}

function CommunityCard({ community }: { community: Row }) {
  const overlaps = asRows(community.overlapping_communities);
  const recommendation = text(community.merge_recommendation, 'preserve_for_context');
  const review = recommendation === 'review_possible_duplicate';
  const explanation = text(community.community_explanation);
  return (
    <Card>
      <CardHeader>
        <Eyebrow>Community · {shortId(text(community.community_id))}</Eyebrow>
        <CardTitle>{text(community.title, text(community.community_id, 'Community'))}</CardTitle>
        <CardDescription className="text-pretty">{text(community.summary)}</CardDescription>
        <CardAction>
          <Badge variant={review ? 'destructive' : 'outline'}>
            {review ? <GitMerge data-icon="inline-start" /> : <ShieldCheck data-icon="inline-start" />}
            {labelize(recommendation)}
          </Badge>
        </CardAction>
      </CardHeader>

      <CardContent className="flex flex-col gap-4">
        <KeyValueList>
          <KeyValue label="Memories">{number(community.member_count)}</KeyValue>
          <KeyValue label="Cohesion">{number(community.cohesion_score).toFixed(2)}</KeyValue>
          <KeyValue label="Updated">{formatTime(text(community.updated_at))}</KeyValue>
        </KeyValueList>

        {explanation && <p className="text-xs text-pretty text-muted-foreground">{explanation}</p>}

        <Separator />

        <div className="flex flex-col gap-2">
          <Eyebrow>Overlapping communities</Eyebrow>
          {overlaps.length > 0 ? (
            <ul className="flex flex-col *:border-b *:last:border-b-0">
              {overlaps.map((overlap) => (
                <li className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-2" key={String(overlap.id)}>
                  <span className="text-xs font-medium">{text(overlap.title, text(overlap.community_id, 'Community'))}</span>
                  <span className="font-mono text-xs text-muted-foreground">
                    {number(overlap.shared_member_count)} shared · {percent(number(overlap.member_overlap_ratio))} member overlap
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-muted-foreground">No overlap detected in the current summary set.</p>
          )}
        </div>

        <Collapsible>
          <CollapsibleTrigger render={<Button variant="ghost" size="sm" className="-ml-2.5" />}>
            Member node ids
          </CollapsibleTrigger>
          <CollapsibleContent>
            <pre className="mt-2 max-h-56 overflow-auto rounded-lg border bg-background p-3 font-mono text-xs text-muted-foreground">
              {JSON.stringify(community.member_nodes_json ?? [], null, 2)}
            </pre>
          </CollapsibleContent>
        </Collapsible>
      </CardContent>
    </Card>
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
