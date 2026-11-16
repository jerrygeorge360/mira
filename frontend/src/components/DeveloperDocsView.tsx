import { ArrowUpRight, BookOpen, Cable, Code2, KeyRound, ShieldCheck } from 'lucide-react';

const API_SCOPES = [
  'memories:read',
  'memories:write',
  'memories:delete',
  'documents:read',
  'documents:write',
  'documents:delete',
  'usage:read',
];

export default function DeveloperDocsView() {
  const apiBase = `${window.location.origin}/v1`;
  const mcpEndpoint = `${window.location.origin}/mcp/v1`;
  const writeExample = `curl ${apiBase}/memories \\
  -H "Authorization: Bearer YOUR_MIRA_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"namespace":"my-app","content":"The user prefers concise answers"}'`;
  const mcpConfig = JSON.stringify(
    {
      mcpServers: {
        mira: {
          url: mcpEndpoint,
          headers: { Authorization: 'Bearer YOUR_MIRA_API_KEY' },
        },
      },
    },
    null,
    2,
  );

  return (
    <div className="developer-docs-view">
      <header className="view-header developer-docs-header">
        <div>
          <div className="developer-kicker"><BookOpen size={14} /> MIRA DEVELOPER DOCS</div>
          <h2>Build with MIRA</h2>
          <p>Connect an app or agent to MIRA memory with the REST API or MCP.</p>
        </div>
        <a className="developer-button" href="/developers/dashboard">
          <KeyRound size={14} /> Manage projects and keys <ArrowUpRight size={14} />
        </a>
      </header>

      <div className="developer-docs-layout">
        <nav className="developer-docs-toc" aria-label="Developer documentation">
          <a href="#docs-quickstart">Quickstart</a>
          <a href="#docs-auth">Authentication</a>
          <a href="#docs-rest">REST API</a>
          <a href="#docs-mcp">MCP</a>
          <a href="#docs-scopes">Scopes and namespaces</a>
        </nav>

        <main className="developer-docs-content">
          <section id="docs-quickstart" className="developer-docs-section">
            <div className="developer-docs-eyebrow"><Code2 size={14} /> QUICKSTART</div>
            <h3>Write your first memory</h3>
            <p>Create a project and API key in the developer dashboard, then send a memory to your app’s namespace.</p>
            <div className="developer-docs-code-label"><span>POST</span> {apiBase}/memories</div>
            <pre className="developer-code"><code>{writeExample}</code></pre>
            <p className="developer-docs-note">A successful write returns an accepted memory ID. Search it later with the same project key and namespace.</p>
          </section>

          <section id="docs-auth" className="developer-docs-section">
            <div className="developer-docs-eyebrow"><ShieldCheck size={14} /> AUTHENTICATION</div>
            <h3>Use a project API key</h3>
            <p>Send the key in the Authorization header. MIRA displays a new key once when it is created, so copy it into your secret manager.</p>
            <pre className="developer-code"><code>Authorization: Bearer YOUR_MIRA_API_KEY</code></pre>
            <p className="developer-docs-note">Keys are project-scoped. Select only the scopes the integration needs; you can revoke a key from the dashboard.</p>
          </section>

          <section id="docs-rest" className="developer-docs-section">
            <div className="developer-docs-eyebrow"><Code2 size={14} /> REST API · V1</div>
            <h3>Endpoints</h3>
            <p>All public API routes use the <code>/v1</code> prefix. Authenticated routes require a project API key and the listed scope.</p>
            <div className="developer-docs-table-wrap">
              <table className="developer-docs-table">
                <thead><tr><th>Method</th><th>Endpoint</th><th>Scope</th><th>Purpose</th></tr></thead>
                <tbody>
                  <tr><td><code>GET</code></td><td><code>/health</code></td><td>—</td><td>Check API availability.</td></tr>
                  <tr><td><code>POST</code></td><td><code>/memories</code></td><td><code>memories:write</code></td><td>Store a memory in a namespace.</td></tr>
                  <tr><td><code>POST</code></td><td><code>/memories/search</code></td><td><code>memories:read</code></td><td>Search memory; choose auto, quick, deep, or relational mode.</td></tr>
                  <tr><td><code>GET</code></td><td><code>/memories/&#123;memory_id&#125;</code></td><td><code>memories:read</code></td><td>Read one memory. Pass <code>namespace</code> as a query parameter.</td></tr>
                  <tr><td><code>DELETE</code></td><td><code>/memories/&#123;memory_id&#125;</code></td><td><code>memories:delete</code></td><td>Forget one memory in the selected namespace.</td></tr>
                  <tr><td><code>POST</code></td><td><code>/documents</code></td><td><code>documents:write</code></td><td>Upload a document as multipart form data.</td></tr>
                  <tr><td><code>GET</code></td><td><code>/documents</code></td><td><code>documents:read</code></td><td>List documents for a namespace.</td></tr>
                  <tr><td><code>DELETE</code></td><td><code>/documents/&#123;document_id&#125;</code></td><td><code>documents:delete</code></td><td>Delete a document and retract its evidence.</td></tr>
                  <tr><td><code>GET</code></td><td><code>/usage</code></td><td><code>usage:read</code></td><td>Read usage for the API key.</td></tr>
                </tbody>
              </table>
            </div>
          </section>

          <section id="docs-mcp" className="developer-docs-section">
            <div className="developer-docs-eyebrow"><Cable size={14} /> MCP</div>
            <h3>Connect an MCP client</h3>
            <p>Use Streamable HTTP with a project key. MCP and REST share the same project, namespace, scopes, quotas, and memory services.</p>
            <div className="developer-docs-code-label"><span>ENDPOINT</span> {mcpEndpoint}</div>
            <pre className="developer-code"><code>{mcpConfig}</code></pre>
            <div className="developer-tool-list">
              {['remember', 'recall', 'search', 'forget', 'history', 'get_context'].map(name => <code key={name}>{name}</code>)}
            </div>
          </section>

          <section id="docs-scopes" className="developer-docs-section">
            <div className="developer-docs-eyebrow"><ShieldCheck size={14} /> ACCESS BOUNDARIES</div>
            <h3>Scopes and namespaces</h3>
            <p>Scopes limit what a key can do. A namespace separates memory within a project; the same namespace in another project is a separate space.</p>
            <div className="developer-docs-scope-list">
              {API_SCOPES.map(scope => <code key={scope}>{scope}</code>)}
            </div>
            <p className="developer-docs-note">Document upload accepts files up to 10 MB. Project-shared documents require document scopes and use the project’s shared knowledge base.</p>
          </section>
        </main>
      </div>
    </div>
  );
}
