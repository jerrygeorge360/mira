# MIRA developer platform quickstart

## 1. Create a project and key

Sign in at [MIRA](https://mira.ninja), open **Developer Platform**, create a project (for example, `Prep AI`), then create an API key with `memories:write`, `memories:read`, and `usage:read` scopes. Copy the complete key when it is shown; MIRA stores its hash and cannot show the secret again.

Store the key in your server's secret manager as `MIRA_API_KEY`. Do not put it in browser code, source control, or client-side environment variables.

## 2. Save a memory

```bash
curl https://mira.ninja/api/v1/memories \
  -H "Authorization: Bearer $MIRA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "namespace": "student_123",
    "content": "The student struggles with quadratic equations.",
    "metadata": {"source": "prep-ai"}
  }'
```

MIRA returns a memory ID after the observation is stored on the fast path. Background enrichment continues through the existing MIRA worker.

## 3. Search later

```bash
curl https://mira.ninja/api/v1/memories/search \
  -H "Authorization: Bearer $MIRA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "namespace": "student_123",
    "query": "What does this student struggle with?",
    "mode": "auto",
    "limit": 10
  }'
```

The response includes matching evidence, source type, score, and safe provenance where available. Use a returned `mem_...` memory ID with `GET /api/v1/memories/{memory_id}?namespace=student_123` or `DELETE` to forget it. Document evidence includes its public document ID and page details in provenance.

## 4. Connect an MCP client

Configure a Streamable HTTP MCP client to use `https://mira.ninja/mcp/v1`, send the same project API key as a Bearer token, and pass `namespace` on memory tools. See [MCP setup](mcp.md).

## 5. Check usage

The dashboard shows successful memory writes and searches against the monthly plan quota. `GET /api/v1/usage` returns usage recorded for the current key. API keys can be revoked from **Developer Platform → API Keys**; revocation is checked on each request.

External users are identifiers inside a project namespace. They do not need MIRA login accounts. See [namespace isolation](namespaces.md), [API key handling](api-keys.md), and the [REST API](rest-api.md).
