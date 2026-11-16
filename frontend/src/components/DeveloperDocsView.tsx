import { ArrowUpRight, Cable, Code2, KeyRound, ShieldCheck } from 'lucide-react';
import type { ReactNode } from 'react';
import CodeSample from './CodeSample';
import { Eyebrow } from './view';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

/* ─────────────────────────────────────────────────────────
 * DEVELOPER DOCS — REST and MCP reference
 *
 * Laid out like the landing page: a sticky index in the margin,
 * sections separated by hairlines. Every console and snippet is
 * a shadcn CodeBlock; the write and search calls come in cURL,
 * TypeScript and Python. Request and response shapes follow
 * api/schemas/platform.py and api/routes/platform.py.
 * ───────────────────────────────────────────────────────── */

const API_SCOPES = [
  'memories:read',
  'memories:write',
  'memories:delete',
  'documents:read',
  'documents:write',
  'documents:delete',
  'usage:read',
];

const ENDPOINTS: { method: string; path: string; scope?: string; purpose: ReactNode }[] = [
  { method: 'GET', path: '/health', purpose: 'Check API availability.' },
  { method: 'POST', path: '/memories', scope: 'memories:write', purpose: 'Store a memory in a namespace.' },
  { method: 'POST', path: '/memories/search', scope: 'memories:read', purpose: 'Search memory; choose auto, quick, deep, or relational mode.' },
  { method: 'GET', path: '/memories/{memory_id}', scope: 'memories:read', purpose: <>Read one memory. Pass <code className="font-mono">namespace</code> as a query parameter.</> },
  { method: 'DELETE', path: '/memories/{memory_id}', scope: 'memories:delete', purpose: 'Forget one memory in the selected namespace.' },
  { method: 'POST', path: '/documents', scope: 'documents:write', purpose: 'Upload a document as multipart form data.' },
  { method: 'GET', path: '/documents', scope: 'documents:read', purpose: 'List documents for a namespace.' },
  { method: 'DELETE', path: '/documents/{document_id}', scope: 'documents:delete', purpose: 'Delete a document and retract its evidence.' },
  { method: 'GET', path: '/usage', scope: 'usage:read', purpose: 'Read usage for the API key.' },
];

const SECTIONS = [
  { id: 'docs-quickstart', label: 'Quickstart' },
  { id: 'docs-search', label: 'Search memory' },
  { id: 'docs-auth', label: 'Authentication' },
  { id: 'docs-rest', label: 'REST API' },
  { id: 'docs-mcp', label: 'MCP' },
  { id: 'docs-scopes', label: 'Scopes and namespaces' },
];

function Section({ id, eyebrow, icon, title, children }: { id: string; eyebrow: string; icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <section id={id} className="flex scroll-mt-20 flex-col gap-4">
      <div className="flex items-center gap-2 text-signal [&_svg]:size-3.5">
        {icon}
        <Eyebrow className="text-signal">{eyebrow}</Eyebrow>
      </div>
      <h2 className="text-xl font-medium tracking-tight">{title}</h2>
      {children}
    </section>
  );
}

function Lede({ children }: { children: ReactNode }) {
  return <p className="max-w-2xl text-sm leading-relaxed text-pretty text-muted-foreground">{children}</p>;
}

/** One call shown in three languages, in tabs. */
function LanguageTabs({ samples }: { samples: { value: string; label: string; language: string; filename: string; code: string }[] }) {
  return (
    <Tabs defaultValue={samples[0].value} className="gap-2">
      <TabsList>
        {samples.map((s) => (
          <TabsTrigger key={s.value} value={s.value}>
            {s.label}
          </TabsTrigger>
        ))}
      </TabsList>
      {samples.map((s) => (
        <TabsContent key={s.value} value={s.value}>
          <CodeSample code={s.code} language={s.language} filename={s.filename} />
        </TabsContent>
      ))}
    </Tabs>
  );
}

export default function DeveloperDocsView() {
  const apiBase = `${window.location.origin}/v1`;
  const mcpEndpoint = `${window.location.origin}/mcp/v1`;

  const write = [
    {
      value: 'curl',
      label: 'cURL',
      language: 'bash',
      filename: 'write-memory.sh',
      code: `curl ${apiBase}/memories \\
  -H "Authorization: Bearer $MIRA_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"namespace":"my-app","content":"The user prefers concise answers"}'`,
    },
    {
      value: 'ts',
      label: 'TypeScript',
      language: 'ts',
      filename: 'write-memory.ts',
      code: `const response = await fetch("${apiBase}/memories", {
  method: "POST",
  headers: {
    Authorization: \`Bearer \${process.env.MIRA_API_KEY}\`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    namespace: "my-app",
    content: "The user prefers concise answers",
  }),
})

const memory = await response.json() // { id, namespace, status: "accepted" }`,
    },
    {
      value: 'python',
      label: 'Python',
      language: 'python',
      filename: 'write_memory.py',
      code: `import os
import httpx

response = httpx.post(
    "${apiBase}/memories",
    headers={"Authorization": f"Bearer {os.environ['MIRA_API_KEY']}"},
    json={"namespace": "my-app", "content": "The user prefers concise answers"},
)
memory = response.json()  # {"id": ..., "namespace": ..., "status": "accepted"}`,
    },
  ];

  const search = [
    {
      value: 'curl',
      label: 'cURL',
      language: 'bash',
      filename: 'search-memory.sh',
      code: `curl ${apiBase}/memories/search \\
  -H "Authorization: Bearer $MIRA_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"namespace":"my-app","query":"How should answers be written?","mode":"auto","limit":5}'`,
    },
    {
      value: 'ts',
      label: 'TypeScript',
      language: 'ts',
      filename: 'search-memory.ts',
      code: `const response = await fetch("${apiBase}/memories/search", {
  method: "POST",
  headers: {
    Authorization: \`Bearer \${process.env.MIRA_API_KEY}\`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    namespace: "my-app",
    query: "How should answers be written?",
    mode: "auto", // auto · quick · deep · relational
    limit: 5,     // 1–50
  }),
})

const { results, count } = await response.json()`,
    },
    {
      value: 'python',
      label: 'Python',
      language: 'python',
      filename: 'search_memory.py',
      code: `response = httpx.post(
    "${apiBase}/memories/search",
    headers={"Authorization": f"Bearer {os.environ['MIRA_API_KEY']}"},
    json={
        "namespace": "my-app",
        "query": "How should answers be written?",
        "mode": "auto",  # auto, quick, deep, relational
        "limit": 5,      # 1-50
    },
)
results = response.json()["results"]`,
    },
  ];

  const mcpConfig = JSON.stringify(
    { mcpServers: { mira: { url: mcpEndpoint, headers: { Authorization: 'Bearer YOUR_MIRA_API_KEY' } } } },
    null,
    2,
  );

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-10">
      <header className="flex flex-wrap items-end justify-between gap-6">
        <div className="flex max-w-2xl flex-col gap-3">
          <Eyebrow>MIRA developer docs</Eyebrow>
          <h1 className="text-3xl font-medium tracking-tight text-balance sm:text-4xl">Give your agent a memory it can explain.</h1>
          <p className="text-base leading-relaxed text-pretty text-muted-foreground">
            Connect an app or agent to MIRA with the REST API or MCP. Both share the same projects, namespaces, scopes and quotas.
          </p>
        </div>
        <Button size="lg" nativeButton={false} render={<a href="/developers/dashboard" />}>
          <KeyRound data-icon="inline-start" />
          Manage projects and keys
          <ArrowUpRight data-icon="inline-end" />
        </Button>
      </header>

      <div className="grid gap-10 lg:grid-cols-[180px_minmax(0,1fr)]">
        <nav className="hidden lg:block" aria-label="On this page">
          <ol className="sticky top-20 flex flex-col gap-0.5 border-l">
            {SECTIONS.map((s, i) => (
              <li key={s.id}>
                <a
                  href={`#${s.id}`}
                  className="-ml-px flex gap-2 border-l border-transparent py-1 pl-3 text-xs text-muted-foreground transition-colors hover:border-foreground hover:text-foreground"
                >
                  <span className="font-mono text-faint">{String(i + 1).padStart(2, '0')}</span>
                  {s.label}
                </a>
              </li>
            ))}
          </ol>
        </nav>

        <div className="flex min-w-0 flex-col gap-10">
          <Section id="docs-quickstart" eyebrow="Quickstart" icon={<Code2 />} title="Write your first memory">
            <Lede>
              Create a project and API key in the dashboard, then send a memory to your app’s namespace. A successful write
              returns <code className="font-mono text-foreground">201</code> with the memory ID.
            </Lede>
            <LanguageTabs samples={write} />
            <CodeSample
              title="201 Created"
              language="json"
              lineNumbers={false}
              code={JSON.stringify({ id: 'mem_8f21c0aa', namespace: 'my-app', status: 'accepted' }, null, 2)}
            />
          </Section>

          <Separator />

          <Section id="docs-search" eyebrow="Search" icon={<Code2 />} title="Search what it remembers">
            <Lede>
              Search a namespace with a natural-language query. <code className="font-mono text-foreground">auto</code> lets
              MIRA pick quick, relational or deep retrieval; set <code className="font-mono text-foreground">include_project_knowledge</code>{' '}
              to also search the project’s shared documents (needs <code className="font-mono text-foreground">documents:read</code>).
            </Lede>
            <LanguageTabs samples={search} />
          </Section>

          <Separator />

          <Section id="docs-auth" eyebrow="Authentication" icon={<ShieldCheck />} title="Use a project API key">
            <Lede>
              Send the key in the Authorization header. MIRA shows a new key once, when it is created, so put it straight into
              your secret manager. Keys are project-scoped; give each one only the scopes it needs, and revoke it from the
              dashboard.
            </Lede>
            <CodeSample title="Request header" language="bash" lineNumbers={false} code="Authorization: Bearer YOUR_MIRA_API_KEY" />
          </Section>

          <Separator />

          <Section id="docs-rest" eyebrow="REST API · v1" icon={<Code2 />} title="Endpoints">
            <Lede>
              Every public route is under <code className="font-mono text-foreground">{apiBase}</code>. Authenticated routes need a
              project API key with the listed scope.
            </Lede>
            <div className="overflow-hidden rounded-xl border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-20">Method</TableHead>
                    <TableHead>Endpoint</TableHead>
                    <TableHead>Scope</TableHead>
                    <TableHead>Purpose</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {ENDPOINTS.map((e) => (
                    <TableRow key={`${e.method} ${e.path}`}>
                      <TableCell>
                        <Badge variant={e.method === 'DELETE' ? 'destructive' : e.method === 'POST' ? 'secondary' : 'outline'} className="font-mono">
                          {e.method}
                        </Badge>
                      </TableCell>
                      <TableCell className="font-mono">{e.path}</TableCell>
                      <TableCell className="font-mono text-muted-foreground">{e.scope ?? '—'}</TableCell>
                      <TableCell className="whitespace-normal text-muted-foreground">{e.purpose}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </Section>

          <Separator />

          <Section id="docs-mcp" eyebrow="MCP" icon={<Cable />} title="Connect an MCP client">
            <Lede>
              Use Streamable HTTP with a project key. MCP and REST share the same project, namespaces, scopes, quotas and memory
              services. Add this to your client’s MCP configuration:
            </Lede>
            <CodeSample code={mcpConfig} language="json" filename="mcp.json" highlight={[4, 5, 6]} />
            <div className="flex flex-wrap items-center gap-1.5">
              <Eyebrow className="mr-1">Tools</Eyebrow>
              {['remember', 'recall', 'search', 'forget', 'history', 'get_context'].map((name) => (
                <Badge key={name} variant="outline" className="font-mono">
                  {name}
                </Badge>
              ))}
            </div>
          </Section>

          <Separator />

          <Section id="docs-scopes" eyebrow="Access boundaries" icon={<ShieldCheck />} title="Scopes and namespaces">
            <Lede>
              Scopes limit what a key can do. A namespace separates memory within a project; the same namespace in another
              project is a different space.
            </Lede>
            <div className="flex flex-wrap gap-1.5">
              {API_SCOPES.map((scope) => (
                <Badge key={scope} variant="secondary" className="font-mono">
                  {scope}
                </Badge>
              ))}
            </div>
            <p className="max-w-2xl text-xs text-pretty text-muted-foreground">
              Document upload accepts files up to 10 MB. Project-shared documents need document scopes and use the project’s
              shared knowledge base.
            </p>
          </Section>
        </div>
      </div>
    </div>
  );
}
