import {
  Activity, BookOpen, Boxes, Check, Code2, Copy, CreditCard, KeyRound,
  Layers3, Plus, Settings2, Shield, Trash2, Users, X,
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { api, type PlatformNamespace, type PlatformOverview } from '../api/client';

type Tab = 'Overview' | 'Projects' | 'API Keys' | 'Usage' | 'Memories' | 'Knowledge Bases' | 'MCP' | 'Billing' | 'Settings';
const TABS: { name: Tab; icon: React.ReactNode }[] = [
  { name: 'Overview', icon: <Activity size={15} /> },
  { name: 'Projects', icon: <Boxes size={15} /> },
  { name: 'API Keys', icon: <KeyRound size={15} /> },
  { name: 'Usage', icon: <Layers3 size={15} /> },
  { name: 'Memories', icon: <Users size={15} /> },
  { name: 'Knowledge Bases', icon: <BookOpen size={15} /> },
  { name: 'MCP', icon: <Code2 size={15} /> },
  { name: 'Billing', icon: <CreditCard size={15} /> },
  { name: 'Settings', icon: <Settings2 size={15} /> },
];
const SCOPES = [
  'memories:read', 'memories:write', 'memories:delete',
  'documents:read', 'documents:write', 'documents:delete', 'usage:read',
];

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

  async function startSubscription(plan: 'developer' | 'pro' | 'scale') {
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

  if (loading && !overview) return <div className="view-empty"><div className="view-empty-msg">Loading developer platform...</div></div>;
  if (!overview) return <div className="view-empty"><div className="view-empty-msg">Developer platform unavailable</div><div className="view-empty-hint">{error || 'Sign in with a MIRA account to continue.'}</div></div>;

  const plan = overview.plans[overview.organization.plan] ?? overview.plans.free;
  const allKeys = overview.api_keys;
  const liveKeys = allKeys.filter(key => !key.revoked_at);

  return (
    <div className="developer-platform-view">
      <header className="view-header developer-platform-header">
        <div>
          <div className="developer-kicker"><Code2 size={14} /> MIRA DEVELOPER PLATFORM</div>
          <h2>Build with MIRA</h2>
          <p>Projects, API keys, external memory namespaces, and billing.</p>
        </div>
        <div className="developer-org-switcher">
          <label htmlFor="platform-org">Organization</label>
          <select id="platform-org" value={organizationId} onChange={event => { setOrganizationId(event.target.value); void reload(event.target.value); }}>
            {overview.organizations.map(org => <option value={org.id} key={org.id}>{org.name}</option>)}
          </select>
          <button className="developer-button secondary" onClick={() => setShowOrganizationForm(value => !value)}><Plus size={14} /> Organization</button>
        </div>
      </header>

      {showOrganizationForm && (
        <form className="developer-inline-form" onSubmit={event => void addOrganization(event)}>
          <input value={organizationName} onChange={event => setOrganizationName(event.target.value)} placeholder="Organization name" maxLength={80} required />
          <button className="developer-button" disabled={busy}>Create organization</button>
          <button type="button" className="developer-button secondary" onClick={() => setShowOrganizationForm(false)}>Cancel</button>
        </form>
      )}
      {error && <div className="developer-alert error" role="alert">{error}</div>}
      {notice && <div className="developer-alert success" role="status">{notice}</div>}

      <nav className="developer-tabs" aria-label="Developer platform sections">
        {TABS.map(item => <button key={item.name} className={tab === item.name ? 'active' : ''} onClick={() => setTab(item.name)}>{item.icon}<span>{item.name}</span></button>)}
      </nav>

      {tab === 'Overview' && <OverviewTab overview={overview} planName={plan.name} onSwitch={setTab} />}
      {tab === 'Projects' && (
        <section className="developer-panel">
          <div className="developer-panel-title"><div><h3>Projects</h3><p>Keys and usage stay attached to their project.</p></div></div>
          <form className="developer-form-row" onSubmit={event => void addProject(event)}>
            <input value={projectName} onChange={event => setProjectName(event.target.value)} placeholder="e.g. Prep AI" maxLength={80} required />
            <select value={environment} onChange={event => setEnvironment(event.target.value as 'development' | 'production')}><option value="production">Production</option><option value="development">Development</option></select>
            <button className="developer-button" disabled={busy}><Plus size={14} /> Create project</button>
          </form>
          <div className="developer-table-wrap"><table className="developer-table"><thead><tr><th>Project</th><th>Environment</th><th>Created</th></tr></thead><tbody>{overview.projects.map(project => <tr key={project.id}><td><strong>{project.name}</strong><small>{project.id}</small></td><td><span className={`developer-badge ${project.environment}`}>{project.environment}</span></td><td>{formatDate(project.created_at)}</td></tr>)}</tbody></table></div>
        </section>
      )}
      {tab === 'API Keys' && (
        <section className="developer-panel">
          <div className="developer-panel-title"><div><h3>API keys</h3><p>Create scoped keys for one MIRA project. The secret is shown once.</p></div><span className="developer-count">{liveKeys.length} active</span></div>
          <form className="developer-key-form" onSubmit={event => void addKey(event)}>
            <div className="developer-form-row">
              <input value={keyName} onChange={event => setKeyName(event.target.value)} placeholder="Key name, e.g. Prep AI server" maxLength={80} required />
              <select value={keyProject} onChange={event => setKeyProject(event.target.value)} required><option value="" disabled>Select a project</option>{overview.projects.map(project => <option key={project.id} value={project.id}>{project.name} · {project.environment}</option>)}</select>
              <input aria-label="Optional key expiry" type="datetime-local" value={keyExpiry} onChange={event => setKeyExpiry(event.target.value)} />
              <button className="developer-button" disabled={busy || keyScopes.length === 0}><Plus size={14} /> Create key</button>
            </div>
            <div className="developer-scope-list">{SCOPES.map(scope => <label key={scope}><input type="checkbox" checked={keyScopes.includes(scope)} onChange={event => setKeyScopes(value => event.target.checked ? [...value, scope] : value.filter(item => item !== scope))} />{scope}</label>)}</div>
          </form>
          <div className="developer-table-wrap"><table className="developer-table"><thead><tr><th>Name</th><th>Scopes</th><th>Last used</th><th>Status</th><th /></tr></thead><tbody>{allKeys.map(key => <tr key={key.id}><td><strong>{key.name}</strong><small><code>{key.prefix}…</code> · {key.project_name}</small></td><td><div className="developer-scope-tags">{key.scopes.map(scope => <code key={scope}>{scope}</code>)}</div></td><td>{formatDate(key.last_used_at)}</td><td><span className={`developer-badge ${key.revoked_at ? 'revoked' : 'active'}`}>{key.revoked_at ? 'Revoked' : key.expires_at && new Date(key.expires_at) < new Date() ? 'Expired' : 'Active'}</span></td><td>{!key.revoked_at && <button className="developer-icon-button danger" title={`Revoke ${key.name}`} onClick={() => { if (window.confirm(`Revoke ${key.name}? It will stop working immediately.`)) void runAction(() => api.revokePlatformKey(key.id), 'API key revoked.'); }}><Trash2 size={15} /></button>}</td></tr>)}</tbody></table></div>
          <p className="developer-footnote"><Shield size={14} /> MIRA stores only a cryptographic hash. Revocation takes effect on the next request.</p>
        </section>
      )}
      {tab === 'Usage' && <UsageTab overview={overview} />}
      {tab === 'Memories' && <NamespaceTab title="Memory namespaces" detail="An external namespace maps to one isolated MIRA workspace inside its project." namespaces={namespaces} type="memories" />}
      {tab === 'Knowledge Bases' && <NamespaceTab title="Knowledge bases" detail="Documents uploaded through the developer API are stored in each namespace's private Knowledge Base." namespaces={namespaces} type="documents" />}
      {tab === 'MCP' && <McpTab />}
      {tab === 'Billing' && <BillingTab overview={overview} billingEmail={billingEmail} setBillingEmail={setBillingEmail} busy={busy} onSubscribe={planId => void startSubscription(planId)} onCancel={() => void runAction(async () => { const result = await api.cancelPlatformSubscription(organizationId); window.location.assign(result.manage_url); }, 'Use the Paystack page to cancel. MIRA will update the plan after Paystack confirms it.')} />}
      {tab === 'Settings' && <section className="developer-panel developer-settings"><div className="developer-panel-title"><div><h3>Organization settings</h3><p>Organization identity and current developer access.</p></div></div><form className="developer-form-row" onSubmit={event => { event.preventDefault(); void runAction(() => api.updateOrganization(organizationId, settingsName), 'Organization updated.'); }}><label>Organization name<input value={settingsName} onChange={event => setSettingsName(event.target.value)} maxLength={80} required /></label><button className="developer-button" disabled={busy}>Save changes</button></form><div className="developer-kv"><span>Slug</span><code>{overview.organization.slug}</code></div><div className="developer-kv"><span>Organization ID</span><code>{overview.organization.id}</code></div><div className="developer-kv"><span>Active projects / plan limit</span><strong>{overview.projects.length} / {plan.projects}</strong></div><div className="developer-kv"><span>Active API keys / plan limit</span><strong>{liveKeys.length} / {plan.api_keys}</strong></div></section>}

      {createdSecret && <div className="developer-modal-backdrop" role="presentation" onClick={() => setCreatedSecret('')}><section className="developer-secret-modal" role="dialog" aria-modal="true" aria-labelledby="secret-title" onClick={event => event.stopPropagation()}><button className="developer-modal-close" aria-label="Close" onClick={() => setCreatedSecret('')}><X size={17} /></button><div className="developer-secret-icon"><KeyRound size={20} /></div><h3 id="secret-title">Copy your API key now</h3><p>You won't be able to see it again after closing this window.</p><textarea readOnly value={createdSecret} onFocus={event => event.currentTarget.select()} /><button className="developer-button wide" onClick={() => void navigator.clipboard.writeText(createdSecret).then(() => setNotice('API key copied to clipboard.'))}><Copy size={15} /> Copy API key</button><button className="developer-button secondary wide" onClick={() => setCreatedSecret('')}><Check size={15} /> Done</button></section></div>}
    </div>
  );
}

function OverviewTab({ overview, planName, onSwitch }: { overview: PlatformOverview; planName: string; onSwitch: (tab: Tab) => void }) {
  return <>
    <div className="admin-metric-grid developer-metrics">
      <Metric label="Memory writes" value={overview.usage.memory_writes.used.toLocaleString()} detail={`${overview.usage.memory_writes.limit.toLocaleString()} this month`} />
      <Metric label="Retrievals" value={overview.usage.retrievals.used.toLocaleString()} detail={`${overview.usage.retrievals.limit.toLocaleString()} this month`} />
      <Metric label="API requests" value={overview.usage.api_requests.toLocaleString()} detail="Authenticated requests this month" />
      <Metric label="Namespaces" value={String(overview.namespaces)} detail={`${overview.documents} documents uploaded`} />
    </div>
    <div className="developer-dashboard-grid">
      <section className="developer-panel"><div className="developer-panel-title"><div><h3>{overview.organization.name}</h3><p>Current organization</p></div><span className="developer-badge active">{planName}</span></div><div className="developer-kv"><span>Billing status</span><strong>{overview.organization.subscription_status}</strong></div><div className="developer-kv"><span>Projects</span><strong>{overview.projects.length}</strong></div><div className="developer-kv"><span>Active API keys</span><strong>{overview.api_keys.filter(key => !key.revoked_at).length}</strong></div><button className="developer-text-button" onClick={() => onSwitch('Billing')}>Manage plan <span>→</span></button></section>
      <section className="developer-panel"><div className="developer-panel-title"><div><h3>Get started</h3><p>Connect a server or agent in a few minutes.</p></div></div><ol className="developer-steps"><li>Create a project for your app.</li><li>Create a scoped API key and copy it once.</li><li>Send a memory with a project namespace.</li></ol><button className="developer-button" onClick={() => onSwitch('API Keys')}><KeyRound size={14} /> Create an API key</button></section>
    </div>
  </>;
}

function UsageTab({ overview }: { overview: PlatformOverview }) {
  const operations = Object.entries(overview.usage.by_operation);
  return <section className="developer-panel"><div className="developer-panel-title"><div><h3>Usage this month</h3><p>Successful writes and searches count toward monthly quotas. All authenticated request outcomes are metered.</p></div></div><QuotaBar label="Memory writes" used={overview.usage.memory_writes.used} limit={overview.usage.memory_writes.limit} /><QuotaBar label="Retrievals" used={overview.usage.retrievals.used} limit={overview.usage.retrievals.limit} /><div className="developer-usage-summary"><div><span>Documents uploaded</span><strong>{overview.usage.documents_uploaded}</strong></div><div><span>API requests</span><strong>{overview.usage.api_requests.toLocaleString()}</strong></div><div><span>Current plan</span><strong>{overview.organization.plan}</strong></div></div><div className="developer-table-wrap"><table className="developer-table"><thead><tr><th>Operation</th><th>Requests</th><th>Successful</th><th>Bytes ingested</th></tr></thead><tbody>{operations.length ? operations.map(([name, item]) => <tr key={name}><td><code>{name}</code></td><td>{item.requests}</td><td>{item.succeeded}</td><td>{(item.bytes_ingested ?? 0).toLocaleString()}</td></tr>) : <tr><td colSpan={4} className="developer-empty-cell">No public API usage in this month yet.</td></tr>}</tbody></table></div></section>;
}

function NamespaceTab({ title, detail, namespaces, type }: { title: string; detail: string; namespaces: PlatformNamespace[]; type: 'memories' | 'documents' }) {
  return <section className="developer-panel"><div className="developer-panel-title"><div><h3>{title}</h3><p>{detail}</p></div></div><div className="developer-table-wrap"><table className="developer-table"><thead><tr><th>Namespace</th><th>Project</th><th>{type === 'memories' ? 'Memories' : 'Documents'}</th><th>Created</th></tr></thead><tbody>{namespaces.length ? namespaces.map(item => <tr key={`${item.project_id}:${item.namespace}`}><td><code>{item.namespace}</code></td><td>{item.project_name}</td><td>{type === 'memories' ? item.memories : item.documents}</td><td>{formatDate(item.created_at)}</td></tr>) : <tr><td colSpan={4} className="developer-empty-cell">Namespaces appear when an API key first writes, searches, or uploads.</td></tr>}</tbody></table></div><p className="developer-footnote"><Shield size={14} /> The same namespace text in a different project resolves to a separate memory space.</p></section>;
}

function McpTab() {
  const endpoint = `${window.location.origin}/mcp/v1`;
  const snippet = JSON.stringify({ mcpServers: { mira: { url: endpoint, headers: { Authorization: 'Bearer YOUR_MIRA_API_KEY' } } } }, null, 2);
  return <section className="developer-panel"><div className="developer-panel-title"><div><h3>Connect an MCP client</h3><p>Use a project API key. Pass the same namespace to share memory across agents.</p></div></div><div className="developer-kv"><span>Streamable HTTP endpoint</span><code>{endpoint}</code></div><pre className="developer-code"><code>{snippet}</code></pre><div className="developer-tool-list">{['remember', 'recall', 'search', 'forget', 'history', 'get_context'].map(name => <code key={name}>{name}</code>)}</div><p className="developer-footnote">MCP calls use the same project, namespace, API-key scopes, quotas, and memory services as REST.</p></section>;
}

function BillingTab({ overview, billingEmail, setBillingEmail, busy, onSubscribe, onCancel }: { overview: PlatformOverview; billingEmail: string; setBillingEmail: (value: string) => void; busy: boolean; onSubscribe: (plan: 'developer' | 'pro' | 'scale') => void; onCancel: () => void }) {
  const current = overview.organization.plan;
  return <div className="developer-billing"><section className="developer-panel"><div className="developer-panel-title"><div><h3>Billing</h3><p>Plan changes take effect only after Paystack confirms the payment.</p></div><span className="developer-badge active">{current} · {overview.organization.subscription_status}</span></div><label className="developer-email-field">Billing email<input type="email" value={billingEmail} onChange={event => setBillingEmail(event.target.value)} placeholder="you@company.com" /></label><div className="developer-plan-grid">{Object.entries(overview.plans).map(([id, item]) => <article className={`developer-plan-card${id === current ? ' current' : ''}`} key={id}><div><h4>{item.name}</h4><strong>{formatPrice(item.monthly_price_minor, item.currency)}</strong><span>{item.monthly_price_minor == null ? 'Contact us' : 'per month'}</span></div><ul><li>{item.memory_writes_monthly.toLocaleString()} memory writes</li><li>{item.retrievals_monthly.toLocaleString()} retrievals</li><li>{item.projects} projects · {item.api_keys} keys</li></ul>{id === current ? <span className="developer-current-plan"><Check size={14} /> Current plan</span> : id === 'free' ? <span className="developer-footnote">Included</span> : current !== 'free' ? <span className="developer-footnote">Contact MIRA to change a paid plan</span> : <button className="developer-button" disabled={busy || !billingEmail || id === 'scale'} onClick={() => onSubscribe(id as 'developer' | 'pro' | 'scale')}>{id === 'scale' ? 'Contact MIRA' : 'Upgrade'}</button>}</article>)}</div>{current !== 'free' && overview.organization.subscription_status === 'active' && <button className="developer-button secondary" onClick={onCancel}>Manage or cancel subscription on Paystack</button>}</section></div>;
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <section className="admin-metric"><div><Activity size={18} /></div><span>{label}</span><strong>{value}</strong><p>{detail}</p></section>;
}

function QuotaBar({ label, used, limit }: { label: string; used: number; limit: number }) {
  const percentage = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  return <div className="developer-quota"><div><span>{label}</span><strong>{used.toLocaleString()} / {limit.toLocaleString()}</strong></div><div className="developer-progress"><i style={{ width: `${percentage}%` }} /></div></div>;
}

function formatDate(value?: string | null) {
  if (!value) return 'Never';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString();
}

function formatPrice(minor: number | null, currency: string) {
  if (minor == null) return 'Contact us';
  return new Intl.NumberFormat('en-NG', { style: 'currency', currency, maximumFractionDigits: 0 }).format(minor / 100);
}

function messageOf(cause: unknown) {
  return cause instanceof Error ? cause.message.replace(/^API \d+: /, '') : 'Something went wrong. Please try again.';
}
