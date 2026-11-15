import {
  ArrowRight,
  CheckCircle,
  Clock,
  FileText,
  Flame,
  Layers,
  MessageSquare,
  Shield,
} from 'lucide-react';
import { api } from '../api/client';
import { useApp } from '../context/AppContext';
import { useLiveData } from '../api/useLiveData';
import { ViewStatus } from './ViewStatus';
import { Eyebrow, ViewHeader, ViewPage } from './view';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty';

type Row = Record<string, unknown>;

const GROUPS = [
  { key: 'corrections', title: 'Active corrections', types: ['correction'], statuses: ['provisional', 'hydrated', 'confirmed'], icon: Shield },
  { key: 'constraints', title: 'Constraints', types: ['active_constraint', 'current_goal'], statuses: ['provisional', 'hydrated', 'confirmed'], icon: Layers },
  { key: 'decisions', title: 'Decisions', types: ['decision'], statuses: ['provisional', 'hydrated', 'confirmed'], icon: CheckCircle },
  { key: 'questions', title: 'Open questions', types: ['open_question'], statuses: ['provisional', 'hydrated', 'confirmed'], icon: MessageSquare },
  { key: 'pending', title: 'Pending promotion', promotion: ['eligible', 'pending_confirmation'], icon: Flame },
  { key: 'inactive', title: 'Recently expired', statuses: ['resolved', 'expired', 'rejected', 'superseded'], icon: Clock },
] as const;

export default function WorkingSetView() {
  const { sessionId, setView, memoryRefreshKey } = useApp();
  const { data, status } = useLiveData(
    () => (sessionId ? api.sessionWorkingSet(sessionId) : Promise.reject(new Error('no session'))),
    [sessionId, memoryRefreshKey],
  );
  const rows = (data?.items as Row[] | undefined) ?? [];

  return (
    <ViewPage>
      <ViewHeader
        title="Session Working Set"
        description="Current-session memory that can steer the next answer, with source, usage, and promotion evidence."
      />
      {rows.length === 0 ? (
        <WorkingSetEmpty
          status={sessionId ? status : 'live'}
          hasSession={Boolean(sessionId)}
          onOpenChat={() => setView('Chat')}
        />
      ) : (
        <div className="flex flex-col gap-8">
          {GROUPS.map((group) => {
            const items = rows.filter((row) => inGroup(row, group));
            if (items.length === 0) return null;
            const Icon = group.icon;
            return (
              <section className="flex flex-col gap-3" key={group.key}>
                <div className="flex items-center gap-2 border-b pb-2">
                  <Icon className="size-4 text-muted-foreground" aria-hidden="true" />
                  <h3 className="text-sm font-medium">{group.title}</h3>
                  <Badge variant="outline" className="font-mono">{items.length}</Badge>
                </div>
                <div className="grid items-start gap-4 lg:grid-cols-2">
                  {items.map((item) => <WorkingSetCard key={String(item.id)} item={item} />)}
                </div>
              </section>
            );
          })}
        </div>
      )}
    </ViewPage>
  );
}

function WorkingSetEmpty({
  status,
  hasSession,
  onOpenChat,
}: {
  status: 'loading' | 'live' | 'offline';
  hasSession: boolean;
  onOpenChat: () => void;
}) {
  if (status !== 'live') {
    return (
      <ViewStatus
        status={status}
        emptyLabel="No working-set items."
        hint="Corrections, constraints, decisions, and open questions appear here as you talk to MIRA."
      />
    );
  }
  return (
    <Empty className="border">
      <EmptyHeader>
        <EmptyTitle>{hasSession ? 'No active working-set items' : 'No live session yet'}</EmptyTitle>
        <EmptyDescription>
          This page shows memory that can affect the next answer immediately — corrections, constraints,
          decisions and open questions — before the slow-path worker turns it into durable facts, graph
          edges, reflections, or foresight.
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button variant="outline" onClick={onOpenChat}>
          Open Chat
        </Button>
      </EmptyContent>
    </Empty>
  );
}

function WorkingSetCard({ item }: { item: Row }) {
  const source = firstRecord(item.source_messages);
  const supersededItems = asRows(item.superseded_items);
  const durable = asRows(item.durable_memory);
  const usageCount = number(item.usage_count);
  const priority = priorityLabel(number(item.priority));
  const evidence = text(item.evidence_span);

  return (
    <Card className={cn(!active(item) && 'opacity-70')}>
      <CardHeader>
        <Eyebrow>{labelize(text(item.type))}</Eyebrow>
        <CardTitle className="text-sm text-pretty">{text(item.content, 'No content recorded.')}</CardTitle>
        <CardAction>
          <Badge variant={priority === 'High' ? 'default' : priority === 'Medium' ? 'secondary' : 'outline'}>
            {priority} priority
          </Badge>
        </CardAction>
      </CardHeader>

      <CardContent className="flex flex-col gap-4">
        <dl className="grid grid-cols-2 gap-x-6 sm:grid-cols-3">
          <Field label="Scope" value={labelize(text(item.scope))} />
          <Field label="Status" value={labelize(text(item.status))} />
          <Field label="Origin" value={labelize(text(item.origin))} />
          <Field label="Explicitness" value={labelize(text(item.explicitness_label))} />
          <Field label="Created" value={formatTime(text(item.created_at))} />
          <Field label="Expires" value={item.expires_at ? formatTime(text(item.expires_at)) : 'End of session'} />
          <Field label="Used" value={`${usageCount} response${usageCount === 1 ? '' : 's'}`} />
          <Field label="Tokens" value={`${number(item.token_cost)}`} />
          <Field label="Promotion" value={labelize(text(item.promotion_status))} />
          <Field label="Durable" value={durable.length ? `${durable.length} hot item${durable.length === 1 ? '' : 's'}` : 'Not promoted'} />
        </dl>

        <div className="flex gap-2">
          <FileText className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
          <div className="flex min-w-0 flex-col gap-0.5">
            <Eyebrow>Source</Eyebrow>
            <span className="text-pretty">{sourceLabel(source)}</span>
          </div>
        </div>

        {evidence ? (
          <blockquote className="border-l-2 border-signal pl-3 text-pretty text-muted-foreground">{evidence}</blockquote>
        ) : null}

        {supersededItems.length > 0 ? (
          <div className="flex gap-2">
            <ArrowRight className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
            <div className="flex min-w-0 flex-col gap-0.5">
              <Eyebrow>Supersedes</Eyebrow>
              {supersededItems.map((row) => (
                <span key={String(row.id)} className="text-pretty text-muted-foreground line-through">
                  {text(row.content, String(row.id))}
                </span>
              ))}
            </div>
          </div>
        ) : null}

        <Collapsible>
          <CollapsibleTrigger render={<Button variant="ghost" size="sm" className="-ml-2.5" />}>
            Usage and raw fields
          </CollapsibleTrigger>
          <CollapsibleContent>
            <pre className="mt-2 max-h-56 overflow-auto rounded-lg border bg-background p-3 font-mono text-xs text-muted-foreground">
              {JSON.stringify({
                id: item.id,
                source_observations: item.source_observations,
                used_in_responses: item.used_in_responses,
                durable_memory: item.durable_memory,
                resolution_reason: item.resolution_reason,
              }, null, 2)}
            </pre>
          </CollapsibleContent>
        </Collapsible>
      </CardContent>
    </Card>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5 border-b py-2">
      <dt className="font-mono text-[11px] tracking-wider text-faint uppercase">{label}</dt>
      <dd className="truncate font-medium" title={value || undefined}>{value || 'Unknown'}</dd>
    </div>
  );
}

function inGroup(
  row: Row,
  group: (typeof GROUPS)[number],
) {
  const type = text(row.type);
  const status = text(row.status);
  const promotion = text(row.promotion_status);
  if ('promotion' in group && group.promotion?.includes(promotion as never)) return true;
  return (
    (!('types' in group) || group.types?.includes(type as never))
    && (!('statuses' in group) || group.statuses?.includes(status as never))
  );
}

function active(item: Row) {
  return item.active === true || ['provisional', 'hydrated', 'confirmed'].includes(text(item.status));
}

function firstRecord(value: unknown): Row | null {
  const rows = asRows(value);
  return rows[0] ?? null;
}

function asRows(value: unknown): Row[] {
  return Array.isArray(value)
    ? value.filter((item): item is Row => Boolean(item) && typeof item === 'object' && !Array.isArray(item))
    : [];
}

function sourceLabel(source: Row | null) {
  if (!source) return 'No source message attached';
  const index = number(source.message_index);
  const content = text(source.content);
  return `Message ${index || '?'} · ${preview(content, 92)}`;
}

function priorityLabel(value: number) {
  if (value >= 0.66) return 'High';
  if (value >= 0.33) return 'Medium';
  return 'Low';
}

function text(value: unknown, fallback = '') {
  return typeof value === 'string' && value ? value : fallback;
}

function number(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function labelize(value: string) {
  return (value || 'unknown').replaceAll('_', ' ');
}

function preview(value: string, max: number) {
  return value.length <= max ? value : `${value.slice(0, max - 1)}…`;
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
