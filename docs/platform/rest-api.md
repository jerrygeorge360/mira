# REST API v1

The production API is available at `https://mira.ninja/api/v1`. Send a project API key using `Authorization: Bearer …`. Request and response bodies use JSON unless the upload endpoint says otherwise.

## Memories

### `POST /memories`

Requires `memories:write`.

```json
{
  "namespace": "student_123",
  "content": "The student struggles with quadratic equations.",
  "metadata": {"source": "prep-ai"}
}
```

Returns `{ "id": "mem_…", "namespace": "…", "status": "accepted" }`. The accepted status means fast-path persistence succeeded; background memory processing uses MIRA's existing worker.

### `POST /memories/search`

Requires `memories:read`. Body: `namespace`, `query`, optional `mode` (`auto`, `quick`, `deep`, `relational`), and `limit` (1–50). The response contains results with a public memory ID, content, source, score, and available provenance. Search uses MIRA's existing retrieval router and workspace-bound retrievers.

### `GET /memories/{memory_id}?namespace=…`

Requires `memories:read`. Returns one memory only if its source belongs to that project namespace.

### `DELETE /memories/{memory_id}?namespace=…`

Requires `memories:delete`. This calls MIRA's forgetting lifecycle; it does not erase provenance records.

## Documents

### `POST /documents`

Requires `documents:write`. Send `multipart/form-data` fields `namespace` and `file`. MIRA reuses its existing Knowledge Base ingestion and private S3 document storage. Uploads are limited to 10 MB and supported text, Markdown, DOCX, and PDF formats; scanned/image-only PDFs are rejected by the current processor.

### `GET /documents?namespace=…`

Requires `documents:read`. Lists documents in that namespace's API Knowledge Base.

### `DELETE /documents/{document_id}?namespace=…`

Requires `documents:delete`. Deletion is constrained to the namespace's internal workspace.

## Usage and health

- `GET /usage` requires `usage:read` and reports current-month usage for the calling API key.
- `GET /health` is public and returns service status.

Authenticated `/v1` requests are metered, including scope errors, quota errors, and other responses. Invalid authentication is not metered. MIRA counts memory/query characters and successful uploaded-file bytes; it does not estimate model tokens. Successful memory writes and searches consume their respective monthly quotas. Quota exhaustion returns `429` with `error: quota_exceeded`.

Responses include `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset` when a key is authenticated. Rate limiting uses SQLite usage events and a 60-second per-key window, which fits the current single-API-container deployment. Multiple API replicas can race the limit; use a shared limiter before horizontally scaling the public API.

## Error codes

| Status | Meaning |
| --- | --- |
| 401 | Missing, invalid, expired, revoked, or inactive key |
| 403 | Key lacks the required scope |
| 404 | Memory or document is not in the requested namespace |
| 413 | Document is larger than 10 MB |
| 422 | Invalid body, namespace, mode, or document |
| 429 | Per-key rate limit or plan quota exceeded |
| 502 | Document storage or processing dependency failed |
