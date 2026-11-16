# Developer MCP

MIRA exposes a project-key MCP endpoint at:

```text
https://mira.ninja/mcp/v1
```

It uses Streamable HTTP. Authenticate with a project API key in the Bearer Authorization header and send a `namespace` argument to every tool. Create distinct keys per agent if you want to revoke or scope them independently; agents with authorized keys on the same project and namespace share memory.

The developer endpoint exposes six stable tools:

- `remember(namespace, content, metadata?)`
- `recall(namespace, memory_id)`
- `search(namespace, query, limit?, mode?)`
- `forget(namespace, memory_id)`
- `history(namespace, limit?)`
- `get_context(namespace, query, limit?)`

MCP checks the same project API key, scopes, monthly quotas, rate limits, and namespace mapping as REST. It delegates to MIRA's existing memory and retrieval services. `forget` uses the existing lifecycle and provenance-preserving behavior.

The existing OAuth/static-token MCP server remains available at `/mcp` for established MIRA integrations. The project-key developer surface is mounted separately at `/mcp/v1` and only lists the six developer tools.

Example client configuration shape:

```json
{
  "mcpServers": {
    "mira": {
      "url": "https://mira.ninja/mcp/v1",
      "headers": {"Authorization": "Bearer YOUR_MIRA_API_KEY"}
    }
  }
}
```
