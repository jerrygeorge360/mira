import {
  Activity, BookOpen, Boxes, Check, CreditCard, KeyRound,
  Layers3, Plus, Settings2, Shield, Trash2, Users,
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { api, type PlatformNamespace, type PlatformOverview } from '../api/client';
import { CHART_COLORS } from './chartPalette';
import CodeSample from './CodeSample';
import LoadingState from './LoadingState';
import { Eyebrow, KeyValue, KeyValueList, Num, Panel, Stat, StatStrip } from './view';
import { EvilBarChart } from '@/components/evilcharts/charts/recharts-bar-chart';
import { EvilRadialChart } from '@/components/evilcharts/charts/recharts-radial-chart';
import type { ChartConfig } from '@/components/evilcharts/ui/recharts-chart';
import { cn } from '@/lib/utils';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import { Field, FieldDescription, FieldGroup, FieldLabel, FieldLegend, FieldSet } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Spinner } from '@/components/ui/spinner';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

/* ─────────────────────────────────────────────────────────
 * DEVELOPER DASHBOARD — projects, keys, usage and billing
 *
 * Built from the same parts as the app's data views: the view
 * primitives (StatStrip, Panel, KeyValue) over shadcn Card,
 * Table, Tabs and form controls, evilcharts for usage, and the
 * shadcn CodeBlock for anything a developer copies. Every number
 * comes from GET /platform; nothing here is sample data.
 * ───────────────────────────────────────────────────────── */

type Tab = 'Overview' | 'Projects' | 'API Keys' | 'Usage' | 'Memories' | 'Knowledge Bases' | 'Billing' | 'Settings';
const TABS: { name: Tab; icon: React.ReactNode }[] = [
  { name: 'Overview', icon: <Activity /> },
  { name: 'Projects', icon: <Boxes /> },
  { name: 'API Keys', icon: <KeyRound /> },
  { name: 'Usage', icon: <Layers3 /> },
  { name: 'Memories', icon: <Users /> },
  { name: 'Knowledge Bases', icon: <BookOpen /> },
  { name: 'Billing', icon: <CreditCard /> },
  { name: 'Settings', icon: <Settings2 /> },
];
const SCOPES = [
  'memories:read', 'memories:write', 'memories:delete',
  'documents:read', 'documents:write', 'documents:delete', 'usage:read',
];
type PaidPlan = 'developer' | 'pro' | 'scale';

export default function DeveloperPlatformView() {
  const [tab, setTab] = useState<Tab>('Overview');
  const [organizationId, setOrganizationId] = useState('');
  const [overview, setOverview] = useState<PlatformOverview | null>(null);
  const [namespaces, setNamespaces] = useState<PlatformNamespace[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [showOrganizationForm, setShowOrganizationForm] = useState(false);
  const [organizationName, setOrganizationName] = useState('');
  const [projectName, setProjectName] = useState('');
  const [environment, setEnvironment] = useState<'development' | 'production'>('production');
  const [keyName, setKeyName] = useState('');
  const [keyProject, setKeyProject] = useState('');
  const [keyScopes, setKeyScopes] = useState<string[]>(['memories:read', 'memories:write', 'usage:read']);
  const [keyExpiry, setKeyExpiry] = useState('');
  const [createdSecret, setCreatedSecret] = useState('');
  const [revoking, setRevoking] = useState<{ id: string; name: string } | null>(null);
  const [billingEmail, setBillingEmail] = useState('');
  const [settingsName, setSettingsName] = useState('');

  async function reload(id = organizationId) {
    setLoading(true);
    setError('');
    try {
      const value = await api.platformOverview(id || undefined);
      setOverview(value);
      setOrganizationId(value.organization.id);
      setSettingsName(value.organization.name);
      setKeyProject(current => value.projects.some(project => project.id === current)
        ? current
        : value.projects[0]?.id ?? '');
    } catch (cause) {
      setError(messageOf(cause));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void reload(organizationId);
    // Load once; organization changes explicitly call reload below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (tab !== 'Memories' && tab !== 'Knowledge Bases') return;
    if (!organizationId) return;
    let active = true;
    api.platformNamespaces(organizationId)
      .then(result => { if (active) setNamespaces(result.namespaces); })
      .catch(cause => { if (active) setError(messageOf(cause)); });
    return () => { active = false; };
  }, [organizationId, tab]);

  async function runAction(action: () => Promise<unknown>, success?: string) {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await action();
      if (success) setNotice(success);
      await reload(organizationId);
    } catch (cause) {
      setError(messageOf(cause));
    } finally {
      setBusy(false);
    }
  }

  async function addOrganization(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      const created = await api.createOrganization(organizationName);
      setOrganizationName('');
      setShowOrganizationForm(false);
      await reload(created.id);
      setNotice('Organization created. Its default production project is ready.');
    } catch (cause) {
      setError(messageOf(cause));
    } finally {
      setBusy(false);
    }
  }

  async function addProject(event: React.FormEvent) {
    event.preventDefault();
    if (!organizationId) return;
    await runAction(
      () => api.createProject({ organization_id: organizationId, name: projectName, environment }),
      'Project created.',
    );
    setProjectName('');
  }

  async function addKey(event: React.FormEvent) {
    event.preventDefault();
    if (!keyProject) return;
    setBusy(true);
    setError('');
    try {
      const result = await api.createPlatformKey({
        project_id: keyProject,
        name: keyName,
        scopes: keyScopes,
        ...(keyExpiry ? { expires_at: new Date(keyExpiry).toISOString() } : {}),
      });
      setCreatedSecret(result.secret);
      setKeyName('');
      setKeyExpiry('');
      await reload(organizationId);
    } catch (cause) {
      setError(messageOf(cause));
    } finally {
      setBusy(false);
    }
  }

  async function startSubscription(plan: PaidPlan) {
    setBusy(true);
    setError('');
    try {
      const result = await api.subscribePlatform({ organization_id: organizationId, plan, email: billingEmail });
      window.location.assign(result.authorization_url);
    } catch (cause) {
      setError(messageOf(cause));
      setBusy(false);
    }
  }

  if (loading && !overview) {
    return (
      <div className="mx-auto max-w-6xl">
        <LoadingState size="page" label="Loading developer platform" />
      </div>
    );
  }
  if (!overview) {
    return (
      <Empty className="mx-auto max-w-xl border">
        <EmptyHeader>
          <EmptyTitle>Developer platform unavailable</EmptyTitle>
          <EmptyDescription>{error || 'Sign in with a MIRA account to continue.'}</EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  const plan = overview.plans[overview.organization.plan] ?? overview.plans.free;
  const allKeys = overview.api_keys;
  const liveKeys = allKeys.filter(key => !key.revoked_at);

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-2">
          <Eyebrow>MIRA developer platform</Eyebrow>
          <h1 className="text-3xl font-medium tracking-tight">Dashboard</h1>
          <p className="text-sm text-muted-foreground">Projects, API keys, external memory namespaces, and billing.</p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <Field className="w-56">
            <FieldLabel htmlFor="platform-org">Organization</FieldLabel>
            <NativeSelect
              id="platform-org"
              value={organizationId}
              onChange={event => { setOrganizationId(event.target.value); void reload(event.target.value); }}
            >
              {overview.organizations.map(org => <NativeSelectOption value={org.id} key={org.id}>{org.name}</NativeSelectOption>)}
            </NativeSelect>
          </Field>
          <Button variant="outline" onClick={() => setShowOrganizationForm(true)}>
            <Plus data-icon="inline-start" />
            Organization
          </Button>
        </div>
      </header>

      {error && <Alert variant="destructive" role="alert"><AlertDescription>{error}</AlertDescription></Alert>}
      {notice && <Alert role="status"><Check /><AlertDescription>{notice}</AlertDescription></Alert>}

      <Tabs value={tab} onValueChange={value => setTab(value as Tab)} className="gap-6">
        <div className="-mx-1 overflow-x-auto px-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          <TabsList variant="line" className="w-max">
            {TABS.map(item => (
              <TabsTrigger key={item.name} value={item.name}>
                {item.icon}
                {item.name}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>

        <TabsContent value="Overview">
          <OverviewTab overview={overview} planName={plan.name} onSwitch={setTab} />
        </TabsContent>

        <TabsContent value="Projects">
          <Panel title="Projects" description="Keys and usage stay attached to their project." contentClassName="flex flex-col gap-5">
            <form onSubmit={event => void addProject(event)} className="flex flex-wrap items-end gap-2">
              <Field className="min-w-56 flex-1">
                <FieldLabel htmlFor="project-name">Project name</FieldLabel>
                <Input id="project-name" value={projectName} onChange={event => setProjectName(event.target.value)} placeholder="e.g. Prep AI" maxLength={80} required />
              </Field>
              <Field className="w-44">
                <FieldLabel htmlFor="project-env">Environment</FieldLabel>
                <NativeSelect id="project-env" value={environment} onChange={event => setEnvironment(event.target.value as 'development' | 'production')}>
                  <NativeSelectOption value="production">Production</NativeSelectOption>
                  <NativeSelectOption value="development">Development</NativeSelectOption>
                </NativeSelect>
              </Field>
              <Button type="submit" disabled={busy}>
                {busy ? <Spinner data-icon="inline-start" /> : <Plus data-icon="inline-start" />}
                Create project
              </Button>
            </form>
            <DataTable
              head={['Project', 'Environment', 'Created']}
              empty="No projects yet."
              rows={overview.projects.map(project => [
                <span key="n" className="flex flex-col"><span className="font-medium">{project.name}</span><span className="font-mono text-muted-foreground">{project.id}</span></span>,
                <EnvBadge key="e" environment={project.environment} />,
                <span key="c" className="text-muted-foreground">{formatDate(project.created_at)}</span>,
              ])}
            />
          </Panel>
        </TabsContent>

        <TabsContent value="API Keys">
          <Panel
            title="API keys"
            description="Create scoped keys for one MIRA project. The secret is shown once."
            action={<Badge variant="outline" className="font-mono"><Num value={liveKeys.length} /> active</Badge>}
            contentClassName="flex flex-col gap-5"
          >
            <form onSubmit={event => void addKey(event)}>
              <FieldGroup>
                <div className="flex flex-wrap items-end gap-2">
                  <Field className="min-w-56 flex-1">
                    <FieldLabel htmlFor="key-name">Key name</FieldLabel>
                    <Input id="key-name" value={keyName} onChange={event => setKeyName(event.target.value)} placeholder="e.g. Prep AI server" maxLength={80} required />
                  </Field>
                  <Field className="w-56">
                    <FieldLabel htmlFor="key-project">Project</FieldLabel>
                    <NativeSelect id="key-project" value={keyProject} onChange={event => setKeyProject(event.target.value)} required>
                      <NativeSelectOption value="" disabled>Select a project</NativeSelectOption>
                      {overview.projects.map(project => <NativeSelectOption key={project.id} value={project.id}>{project.name} · {project.environment}</NativeSelectOption>)}
                    </NativeSelect>
                  </Field>
                  <Field className="w-56">
                    <FieldLabel htmlFor="key-expiry">Expires (optional)</FieldLabel>
                    <Input id="key-expiry" type="datetime-local" value={keyExpiry} onChange={event => setKeyExpiry(event.target.value)} />
                  </Field>
                </div>
                <FieldSet>
                  <FieldLegend variant="label">Scopes</FieldLegend>
                  <FieldDescription>Give the key only what the integration needs.</FieldDescription>
                  <div className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
                    {SCOPES.map(scope => (
                      <Field key={scope} orientation="horizontal">
                        <Checkbox
                          id={`scope-${scope}`}
                          checked={keyScopes.includes(scope)}
                          onCheckedChange={checked => setKeyScopes(value => checked ? [...value, scope] : value.filter(item => item !== scope))}
                        />
                        <FieldLabel htmlFor={`scope-${scope}`} className="font-mono font-normal">{scope}</FieldLabel>
                      </Field>
                    ))}
                  </div>
                </FieldSet>
                <div>
                  <Button type="submit" disabled={busy || keyScopes.length === 0}>
                    {busy ? <Spinner data-icon="inline-start" /> : <Plus data-icon="inline-start" />}
                    Create key
                  </Button>
                </div>
              </FieldGroup>
            </form>
            <DataTable
              head={['Name', 'Scopes', 'Last used', 'Status', '']}
              empty="No API keys yet."
              rows={allKeys.map(key => {
                const expired = Boolean(key.expires_at && new Date(key.expires_at) < new Date());
                return [
                  <span key="n" className="flex flex-col"><span className="font-medium">{key.name}</span><span className="font-mono text-muted-foreground">{key.prefix}… · {key.project_name}</span></span>,
                  <span key="s" className="flex max-w-80 flex-wrap gap-1">{key.scopes.map(scope => <Badge key={scope} variant="secondary" className="font-mono">{scope}</Badge>)}</span>,
                  <span key="l" className="text-muted-foreground">{formatDate(key.last_used_at)}</span>,
                  <Badge key="st" variant={key.revoked_at ? 'destructive' : expired ? 'secondary' : 'outline'} className={!key.revoked_at && !expired ? 'text-signal' : undefined}>
                    {key.revoked_at ? 'Revoked' : expired ? 'Expired' : 'Active'}
                  </Badge>,
                  !key.revoked_at ? (
                    <Button key="r" variant="ghost" size="icon-sm" aria-label={`Revoke ${key.name}`} onClick={() => setRevoking({ id: key.id, name: key.name })}>
                      <Trash2 />
                    </Button>
                  ) : <span key="r" />,
                ];
              })}
            />
            <p className="flex items-center gap-2 text-xs text-muted-foreground"><Shield className="size-3.5" /> MIRA stores only a cryptographic hash. Revocation takes effect on the next request.</p>
          </Panel>
        </TabsContent>

        <TabsContent value="Usage"><UsageTab overview={overview} /></TabsContent>
        <TabsContent value="Memories">
          <NamespaceTab title="Memory namespaces" detail="An external namespace maps to one isolated MIRA workspace inside its project." namespaces={namespaces} type="memories" />
        </TabsContent>
        <TabsContent value="Knowledge Bases">
          <NamespaceTab title="Knowledge bases" detail="Documents uploaded through the developer API are stored in each namespace's private Knowledge Base." namespaces={namespaces} type="documents" />
        </TabsContent>

        <TabsContent value="Billing">
          <BillingTab
            overview={overview}
            billingEmail={billingEmail}
            setBillingEmail={setBillingEmail}
            busy={busy}
            onSubscribe={planId => void startSubscription(planId)}
            onCancel={() => void runAction(async () => { const result = await api.cancelPlatformSubscription(organizationId); window.location.assign(result.manage_url); }, 'Use the Paystack page to cancel. MIRA will update the plan after Paystack confirms it.')}
          />
        </TabsContent>

        <TabsContent value="Settings">
          <Panel title="Organization settings" description="Organization identity and current developer access." contentClassName="flex flex-col gap-5">
            <form onSubmit={event => { event.preventDefault(); void runAction(() => api.updateOrganization(organizationId, settingsName), 'Organization updated.'); }} className="flex flex-wrap items-end gap-2">
              <Field className="min-w-56 flex-1">
                <FieldLabel htmlFor="org-name">Organization name</FieldLabel>
                <Input id="org-name" value={settingsName} onChange={event => setSettingsName(event.target.value)} maxLength={80} required />
              </Field>
              <Button type="submit" disabled={busy}>Save changes</Button>
            </form>
            <KeyValueList>
              <KeyValue label="Slug">{overview.organization.slug}</KeyValue>
              <KeyValue label="Organization ID">{overview.organization.id}</KeyValue>
              <KeyValue label="Active projects / plan limit">{overview.projects.length} / {plan.projects}</KeyValue>
              <KeyValue label="Active API keys / plan limit">{liveKeys.length} / {plan.api_keys}</KeyValue>
            </KeyValueList>
          </Panel>
        </TabsContent>
      </Tabs>

      <Dialog open={showOrganizationForm} onOpenChange={setShowOrganizationForm}>
        <DialogContent>
          <form onSubmit={event => void addOrganization(event)} className="flex flex-col gap-4">
            <DialogHeader>
              <DialogTitle>New organization</DialogTitle>
              <DialogDescription>It starts on the Free plan with a default production project.</DialogDescription>
            </DialogHeader>
            <Field>
              <FieldLabel htmlFor="new-org-name">Organization name</FieldLabel>
              <Input id="new-org-name" value={organizationName} onChange={event => setOrganizationName(event.target.value)} maxLength={80} required autoFocus />
            </Field>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setShowOrganizationForm(false)}>Cancel</Button>
              <Button type="submit" disabled={busy}>{busy && <Spinner data-icon="inline-start" />}Create organization</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(createdSecret)} onOpenChange={open => { if (!open) setCreatedSecret(''); }}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>Copy your API key now</DialogTitle>
            <DialogDescription>You won’t be able to see it again after closing this window. Store it in your secret manager.</DialogDescription>
          </DialogHeader>
          <CodeSample title="MIRA_API_KEY" language="bash" lineNumbers={false} code={createdSecret} />
          <CodeSample
            title="Try it"
            language="bash"
            lineNumbers={false}
            code={`curl ${window.location.origin}/v1/health \\\n  -H "Authorization: Bearer ${createdSecret}"`}
          />
          <DialogFooter>
            <Button onClick={() => setCreatedSecret('')}><Check data-icon="inline-start" />Done</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={revoking !== null} onOpenChange={open => { if (!open) setRevoking(null); }}>
        <AlertDialogContent size="sm">
          <AlertDialogHeader>
            <AlertDialogTitle>Revoke {revoking?.name}?</AlertDialogTitle>
            <AlertDialogDescription>It stops working on its next request. This cannot be undone.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                const target = revoking;
                setRevoking(null);
                if (target) void runAction(() => api.revokePlatformKey(target.id), 'API key revoked.');
              }}
            >
              Revoke key
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

/* ── Tabs ───────────────────────────────────────────────── */

function OverviewTab({ overview, planName, onSwitch }: { overview: PlatformOverview; planName: string; onSwitch: (tab: Tab) => void }) {
  const project = overview.projects[0];
  return (
    <div className="flex flex-col gap-4">
      <StatStrip>
        <Stat label="Memory writes" value={overview.usage.memory_writes.used} detail={<>of <Num value={overview.usage.memory_writes.limit} /> this month</>} />
        <Stat label="Retrievals" value={overview.usage.retrievals.used} detail={<>of <Num value={overview.usage.retrievals.limit} /> this month</>} />
        <Stat label="API requests" value={overview.usage.api_requests} detail="Authenticated requests this month" />
        <Stat label="Namespaces" value={overview.namespaces} detail={<><Num value={overview.documents} /> documents uploaded</>} />
      </StatStrip>
      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <Panel
          title={overview.organization.name}
          description="Current organization"
          action={<Badge className="bg-signal text-signal-foreground">{planName}</Badge>}
          contentClassName="flex flex-col gap-3"
        >
          <KeyValueList>
            <KeyValue label="Billing status">{overview.organization.subscription_status}</KeyValue>
            <KeyValue label="Projects">{overview.projects.length}</KeyValue>
            <KeyValue label="Active API keys">{overview.api_keys.filter(key => !key.revoked_at).length}</KeyValue>
          </KeyValueList>
          <Button variant="link" className="self-start px-0" onClick={() => onSwitch('Billing')}>Manage plan →</Button>
        </Panel>
        <Panel title="Get started" description="Connect a server or agent in a few minutes." contentClassName="flex flex-col gap-4">
          <ol className="flex flex-col gap-2 text-sm">
            {['Create a project for your app.', 'Create a scoped API key and copy it once.', 'Send a memory with a project namespace.'].map((step, i) => (
              <li key={step} className="flex gap-3">
                <span className="flex size-5 shrink-0 items-center justify-center rounded-full border font-mono text-[11px] text-muted-foreground">{i + 1}</span>
                {step}
              </li>
            ))}
          </ol>
          <CodeSample
            title={project ? `Write to ${project.name}` : 'Write a memory'}
            language="bash"
            filename="write-memory.sh"
            code={`curl ${window.location.origin}/v1/memories \\
  -H "Authorization: Bearer $MIRA_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"namespace":"my-app","content":"The user prefers concise answers"}'`}
          />
          <Button className="self-start" onClick={() => onSwitch('API Keys')}><KeyRound data-icon="inline-start" />Create an API key</Button>
        </Panel>
      </div>
    </div>
  );
}

const QUOTA_CONFIG = {
  writes: { label: 'Memory writes', colors: CHART_COLORS.signal },
  retrievals: { label: 'Retrievals', colors: CHART_COLORS.blue },
} satisfies ChartConfig;

const OPERATION_CONFIG = {
  requests: { label: 'Requests', colors: CHART_COLORS.neutral },
  succeeded: { label: 'Succeeded', colors: CHART_COLORS.signal },
} satisfies ChartConfig;

function UsageTab({ overview }: { overview: PlatformOverview }) {
  const operations = Object.entries(overview.usage.by_operation);
  const pct = (used: number, limit: number) => (limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0);
  const quota = [
    { metric: 'writes', used: pct(overview.usage.memory_writes.used, overview.usage.memory_writes.limit) },
    { metric: 'retrievals', used: pct(overview.usage.retrievals.used, overview.usage.retrievals.limit) },
  ];
  const byOperation = operations.map(([name, item]) => ({ operation: name, requests: item.requests, succeeded: item.succeeded }));

  return (
    <div className="flex flex-col gap-4">
      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)]">
        <Panel title="Monthly quota" description="Share of this month’s plan allowance used." contentClassName="flex flex-col gap-2">
          <div className="h-56">
            <EvilRadialChart data={quota} nameKey="metric" config={QUOTA_CONFIG} variant="full" max={100} innerRadius="52%" outerRadius="92%" className="h-full w-full">
              <EvilRadialChart.Tooltip />
              <EvilRadialChart.Legend />
              <EvilRadialChart.RadialBar dataKey="used" showBackground barSize={16} />
            </EvilRadialChart>
          </div>
          <KeyValueList>
            <KeyValue label="Memory writes">
              <Num value={overview.usage.memory_writes.used} /> / {overview.usage.memory_writes.limit.toLocaleString()}
            </KeyValue>
            <KeyValue label="Retrievals">
              <Num value={overview.usage.retrievals.used} /> / {overview.usage.retrievals.limit.toLocaleString()}
            </KeyValue>
          </KeyValueList>
        </Panel>
        <Panel title="Requests by operation" description="All authenticated request outcomes are metered; successful writes and searches count toward quotas.">
          {byOperation.length ? (
            <div className="h-64">
              <EvilBarChart data={byOperation} config={OPERATION_CONFIG} xDataKey="operation" className="h-full w-full" barRadius={6} barCategoryGap={24}>
                <EvilBarChart.Grid />
                <EvilBarChart.XAxis dataKey="operation" />
                <EvilBarChart.Legend />
                <EvilBarChart.Tooltip />
                <EvilBarChart.Bar dataKey="requests" />
                <EvilBarChart.Bar dataKey="succeeded" />
              </EvilBarChart>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No public API usage this month yet.</p>
          )}
        </Panel>
      </div>
      <Panel title="Usage this month">
        <DataTable
          head={['Operation', 'Requests', 'Successful', 'Bytes ingested']}
          empty="No public API usage in this month yet."
          numeric={[1, 2, 3]}
          rows={operations.map(([name, item]) => [
            <span key="o" className="font-mono">{name}</span>,
            item.requests.toLocaleString(),
            item.succeeded.toLocaleString(),
            (item.bytes_ingested ?? 0).toLocaleString(),
          ])}
        />
      </Panel>
    </div>
  );
}

function NamespaceTab({ title, detail, namespaces, type }: { title: string; detail: string; namespaces: PlatformNamespace[]; type: 'memories' | 'documents' }) {
  return (
    <Panel title={title} description={detail} contentClassName="flex flex-col gap-4">
      <DataTable
        head={['Namespace', 'Project', type === 'memories' ? 'Memories' : 'Documents', 'Created']}
        empty="Namespaces appear when an API key first writes, searches, or uploads."
        numeric={[2]}
        rows={namespaces.map(item => [
          <span key="n" className="font-mono">{item.namespace}</span>,
          item.project_name,
          (type === 'memories' ? item.memories : item.documents).toLocaleString(),
          <span key="c" className="text-muted-foreground">{formatDate(item.created_at)}</span>,
        ])}
      />
      <p className="flex items-center gap-2 text-xs text-muted-foreground"><Shield className="size-3.5" /> The same namespace text in a different project resolves to a separate memory space.</p>
    </Panel>
  );
}

/* ── Billing: plans as a pricing grid, then a full comparison ── */

function BillingTab({ overview, billingEmail, setBillingEmail, busy, onSubscribe, onCancel }: {
  overview: PlatformOverview;
  billingEmail: string;
  setBillingEmail: (value: string) => void;
  busy: boolean;
  onSubscribe: (plan: PaidPlan) => void;
  onCancel: () => void;
}) {
  const current = overview.organization.plan;
  const plans = Object.entries(overview.plans);
  const onFree = current === 'free';

  const action = (id: string) => {
    if (id === current) return <Button variant="outline" className="w-full" disabled><Check data-icon="inline-start" />Current plan</Button>;
    if (id === 'free') return <Button variant="ghost" className="w-full" disabled>Included</Button>;
    // Scale is priced per customer; there is no self-serve checkout for it
    if (id === 'scale') return <Button variant="outline" className="w-full" disabled>Contact MIRA</Button>;
    if (!onFree) return <Button variant="ghost" className="w-full" disabled>Contact MIRA to change</Button>;
    return (
      <Button className="w-full" disabled={busy || !billingEmail} onClick={() => onSubscribe(id as PaidPlan)}>
        {busy && <Spinner data-icon="inline-start" />}Upgrade to {overview.plans[id].name}
      </Button>
    );
  };

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex max-w-xl flex-col gap-2">
          <h2 className="text-2xl font-medium tracking-tight">Plans</h2>
          <p className="text-sm text-pretty text-muted-foreground">
            Start free and move up when your agents need more memory. Plan changes take effect once Paystack confirms the payment.
          </p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <Eyebrow>Current</Eyebrow>
          <Badge variant="outline" className="font-mono">{overview.plans[current]?.name ?? current} · {overview.organization.subscription_status}</Badge>
        </div>
      </div>

      {onFree && (
        <Field className="max-w-sm">
          <FieldLabel htmlFor="billing-email">Billing email</FieldLabel>
          <Input id="billing-email" type="email" value={billingEmail} onChange={event => setBillingEmail(event.target.value)} placeholder="you@company.com" />
          <FieldDescription>Paystack sends receipts here. Needed to upgrade.</FieldDescription>
        </Field>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {plans.map(([id, item]) => {
          const isCurrent = id === current;
          return (
            <Card key={id} className={cn('h-full', isCurrent && 'ring-2 ring-signal')}>
              <CardHeader>
                <div className="flex items-center justify-between gap-2">
                  <CardTitle className="text-base">{item.name}</CardTitle>
                  {isCurrent && <Badge className="bg-signal text-signal-foreground">Current</Badge>}
                </div>
                <CardDescription>{PLAN_BLURB[id] ?? ''}</CardDescription>
              </CardHeader>
              <CardContent className="flex flex-1 flex-col gap-5">
                <div className="flex items-baseline gap-1.5">
                  <span className="text-3xl font-medium tracking-tight">{formatPrice(item.monthly_price_minor, item.currency)}</span>
                  {item.monthly_price_minor != null && item.monthly_price_minor > 0 && <span className="text-sm text-muted-foreground">/ month</span>}
                </div>
                <div className="flex flex-col gap-2">
                  <Eyebrow>What’s included</Eyebrow>
                  <ul className="flex flex-col gap-2 text-sm">
                    {[
                      `${item.memory_writes_monthly.toLocaleString()} memory writes / mo`,
                      `${item.retrievals_monthly.toLocaleString()} retrievals / mo`,
                      `${item.projects} ${item.projects === 1 ? 'project' : 'projects'}`,
                      `${item.api_keys} API keys`,
                      `${item.rate_limit_per_minute.toLocaleString()} requests / min`,
                    ].map(line => (
                      <li key={line} className="flex gap-2">
                        <Check className="mt-0.5 size-3.5 shrink-0 text-signal" aria-hidden="true" />
                        {line}
                      </li>
                    ))}
                  </ul>
                </div>
              </CardContent>
              <CardFooter>{action(id)}</CardFooter>
            </Card>
          );
        })}
      </div>

      <Panel title="Compare plans" description="Monthly limits per organization.">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Limit</TableHead>
                {plans.map(([id, item]) => <TableHead key={id} className={cn('text-right', id === current && 'text-signal')}>{item.name}</TableHead>)}
              </TableRow>
            </TableHeader>
            <TableBody>
              {COMPARE_ROWS.map(row => (
                <TableRow key={row.label}>
                  <TableCell className="text-muted-foreground">{row.label}</TableCell>
                  {plans.map(([id, item]) => <TableCell key={id} className="text-right font-mono tabular-nums">{row.value(item)}</TableCell>)}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </Panel>

      {!onFree && overview.organization.subscription_status === 'active' && (
        <div>
          <Button variant="outline" onClick={onCancel}>Manage or cancel subscription on Paystack</Button>
        </div>
      )}
    </div>
  );
}

/** One line under each plan name, describing who it is for. */
const PLAN_BLURB: Record<string, string> = {
  free: 'Try MIRA with one project.',
  developer: 'For a single app in production.',
  pro: 'For teams running several agents.',
  scale: 'High volume, with limits set together.',
};

type PlanRow = PlatformOverview['plans'][string];
const COMPARE_ROWS: { label: string; value: (plan: PlanRow) => string }[] = [
  { label: 'Price / month', value: plan => formatPrice(plan.monthly_price_minor, plan.currency) },
  { label: 'Memory writes', value: plan => plan.memory_writes_monthly.toLocaleString() },
  { label: 'Retrievals', value: plan => plan.retrievals_monthly.toLocaleString() },
  { label: 'Projects', value: plan => plan.projects.toLocaleString() },
  { label: 'API keys', value: plan => plan.api_keys.toLocaleString() },
  { label: 'Requests / minute', value: plan => plan.rate_limit_per_minute.toLocaleString() },
];

/* ── Shared bits ───────────────────────────────────────── */

function DataTable({ head, rows, empty, numeric = [] }: { head: string[]; rows: React.ReactNode[][]; empty: string; numeric?: number[] }) {
  return (
    <div className="overflow-hidden rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            {head.map((h, i) => <TableHead key={`${h}-${i}`} className={numeric.includes(i) ? 'text-right' : undefined}>{h}</TableHead>)}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.length ? rows.map((cells, r) => (
            <TableRow key={r}>
              {cells.map((cell, i) => <TableCell key={i} className={cn(numeric.includes(i) && 'text-right font-mono tabular-nums')}>{cell}</TableCell>)}
            </TableRow>
          )) : (
            <TableRow><TableCell colSpan={head.length} className="py-8 text-center whitespace-normal text-muted-foreground">{empty}</TableCell></TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
}

function EnvBadge({ environment }: { environment: string }) {
  return <Badge variant={environment === 'production' ? 'outline' : 'secondary'} className={environment === 'production' ? 'text-signal' : undefined}>{environment}</Badge>;
}

function formatDate(value?: string | null) {
  if (!value) return 'Never';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString();
}

function formatPrice(minor: number | null, currency: string) {
  if (minor == null) return 'Custom';
  if (minor === 0) return 'Free';
  return new Intl.NumberFormat('en-NG', { style: 'currency', currency, maximumFractionDigits: 0 }).format(minor / 100);
}

function messageOf(cause: unknown) {
  return cause instanceof Error ? cause.message.replace(/^API \d+: /, '') : 'Something went wrong. Please try again.';
}
