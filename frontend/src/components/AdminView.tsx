import { Activity, Boxes, Cable, Check, Cpu, ShieldCheck, Users } from 'lucide-react';
import { useState } from 'react';
import { api } from '../api/client';
import { formatTime, useLiveData } from '../api/useLiveData';
import LoadingState from './LoadingState';
import { KeyValue, KeyValueList, Panel, Stat, StatStrip, ViewHeader, ViewPage } from './view';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import { Progress } from '@/components/ui/progress';
import { Spinner } from '@/components/ui/spinner';

export default function AdminView() {
  const { data, status } = useLiveData(() => api.adminOverview(), []);
  const {
    data: providerData,
    status: providerStatus,
    setData: setProviderData,
  } = useLiveData(() => api.adminProvider(), []);
  const [switchingProvider, setSwitchingProvider] = useState<string | null>(null);

  if (status === 'loading') {
    return (
      <Empty className="border">
        <LoadingState label="Loading platform overview" />
      </Empty>
    );
  }
  if (status === 'offline' || !data) {
    return (
      <Empty className="border">
        <EmptyHeader>
          <EmptyTitle>Administration unavailable</EmptyTitle>
          <EmptyDescription>This view requires an explicitly configured platform administrator.</EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  const workspaceTotal = sumValues(data.workspaces);
  const queueTotal = sumValues(data.queue);
  const queueAttention = (data.queue.failed ?? 0)
    + (data.queue.dead_letter ?? 0)
    + (data.queue.quarantined ?? 0);
  const maxRegistrations = Math.max(1, ...data.registrations_last_30_days.map(item => item.count));

  return (
    <ViewPage>
      <ViewHeader
        title="Administration"
        description="Aggregate product usage and runtime health. No conversation or memory content is exposed."
      >
        <Badge variant="outline">
          <ShieldCheck data-icon="inline-start" />
          Read only
        </Badge>
      </ViewHeader>

      <StatStrip>
        <Stat
          label="Registered people"
          value={data.users.registered}
          detail={`${data.users.new_last_7_days} joined in 7 days`}
        />
        <Stat
          label="Active people"
          value={data.users.active_last_7_days}
          detail="Logged in during the last 7 days"
        />
        <Stat
          label="Active workspaces"
          value={workspaceTotal}
          detail={`${data.workspaces.personal ?? 0} personal · ${data.workspaces.demo ?? 0} demo`}
        />
        <Stat
          label="Active sessions"
          value={data.activity.active_web_sessions}
          detail={`${data.activity.conversations} conversations`}
        />
      </StatStrip>

      <div className="grid items-start gap-4 md:grid-cols-2">
        <Panel title="Model provider" icon={<Cpu />} className="md:col-span-2">
          {providerStatus === 'loading' || !providerData ? (
            <LoadingState label="Loading provider profiles" />
          ) : (
            <div className="grid gap-x-8 gap-y-4 md:grid-cols-2">
              <KeyValueList>
                <KeyValue label="Active profile">{providerData.active ?? 'none'}</KeyValue>
                <KeyValue label="Source">{providerData.source}</KeyValue>
                <KeyValue label="Model">{providerData.model ?? 'not configured'}</KeyValue>
              </KeyValueList>
              <ul className="flex flex-col *:border-b *:last:border-b-0">
                {providerData.providers.map(provider => {
                  const active = provider.name === providerData.active;
                  const switching = switchingProvider === provider.name;
                  return (
                    <li key={provider.name} className="flex items-center justify-between gap-3 py-2">
                      <span className="flex min-w-0 flex-col">
                        <span className="truncate text-xs font-medium">{provider.name}</span>
                        <span className="truncate font-mono text-xs text-muted-foreground">{provider.model}</span>
                      </span>
                      {active ? (
                        <Badge className="bg-signal text-signal-foreground">
                          <Check data-icon="inline-start" />
                          Active
                        </Badge>
                      ) : (
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={switchingProvider !== null}
                          onClick={async () => {
                            setSwitchingProvider(provider.name);
                            try {
                              setProviderData(await api.updateAdminProvider(provider.name));
                            } finally {
                              setSwitchingProvider(null);
                            }
                          }}
                        >
                          {switching && <Spinner data-icon="inline-start" />}
                          {switching ? 'Switching' : 'Use'}
                        </Button>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </Panel>

        <Panel title="Registration" icon={<Users />}>
          <KeyValueList>
            <KeyValue label="Last 7 days">{data.users.new_last_7_days}</KeyValue>
            <KeyValue label="Last 30 days">{data.users.new_last_30_days}</KeyValue>
            <KeyValue label="Active in 7 days">{data.users.active_last_7_days}</KeyValue>
          </KeyValueList>
          {data.registrations_last_30_days.length === 0 ? (
            <p className="pt-3 text-xs text-muted-foreground">No registrations in the last 30 days.</p>
          ) : (
            <ul className="flex flex-col gap-2 pt-4">
              {data.registrations_last_30_days.map(item => (
                <li
                  key={item.date}
                  className="grid grid-cols-[4rem_minmax(0,1fr)_2rem] items-center gap-3 font-mono text-xs"
                >
                  <time dateTime={item.date} className="text-muted-foreground">{formatDate(item.date)}</time>
                  <Progress
                    value={(item.count / maxRegistrations) * 100}
                    aria-label={`${item.count} registrations on ${formatDate(item.date)}`}
                  />
                  <span className="text-right tabular-nums">{item.count}</span>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel title="Runtime activity" icon={<Activity />} contentClassName="flex flex-col gap-3">
          <KeyValueList>
            <KeyValue label="Conversations">{data.activity.conversations}</KeyValue>
            <KeyValue label="Observations">{data.activity.observations}</KeyValue>
            <KeyValue label="Retrieval traces">{data.activity.retrieval_traces}</KeyValue>
            <KeyValue label="Queue records">{queueTotal}</KeyValue>
          </KeyValueList>
          <Alert variant={queueAttention > 0 ? 'destructive' : 'default'}>
            <AlertDescription className="flex items-center justify-between gap-3">
              <span>{queueAttention > 0 ? 'Queue needs attention' : 'No queue failures'}</span>
              <span className="font-mono tabular-nums">{queueAttention}</span>
            </AlertDescription>
          </Alert>
        </Panel>

        <Panel title="OAuth and MCP" icon={<Cable />}>
          <KeyValueList>
            <KeyValue label="Registered clients">{data.oauth.registered_clients}</KeyValue>
            <KeyValue label="Active access tokens">{data.oauth.active_access_tokens}</KeyValue>
            <KeyValue label="Pending work">{data.queue.pending ?? 0}</KeyValue>
            <KeyValue label="Quarantined work">{data.queue.quarantined ?? 0}</KeyValue>
          </KeyValueList>
        </Panel>

        <Panel title="Workspace distribution" icon={<Boxes />}>
          <KeyValueList>
            {Object.entries(data.workspaces).map(([type, count]) => (
              <KeyValue key={type} label={type.replaceAll('_', ' ')}>{count}</KeyValue>
            ))}
          </KeyValueList>
          <p className="pt-3 font-mono text-xs text-faint">Snapshot generated {formatTime(data.generated_at)}</p>
        </Panel>
      </div>
    </ViewPage>
  );
}

function sumValues(values: Record<string, number>): number {
  return Object.values(values).reduce((total, value) => total + value, 0);
}

function formatDate(value: string): string {
  const date = new Date(`${value}T00:00:00Z`);
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
}
