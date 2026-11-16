# API keys

Create keys in **Developer Platform → API Keys**. Each key belongs to one project and inherits its production or development environment:

- Production projects issue `mira_live_…` keys.
- Development projects issue `mira_test_…` keys.

The secret is generated with a cryptographically secure random source, displayed once, and stored as a SHA-256 digest. MIRA keeps only a short display prefix. Authentication compares the supplied digest in constant time. Names, scopes, creation time, optional expiry, and last use are retained for the dashboard.

Available scopes are `memories:read`, `memories:write`, `memories:delete`, `documents:read`, `documents:write`, `documents:delete`, and `usage:read`. Grant only the scopes an application needs. Revoking a key makes it fail on the next request.

Pass a key in the Authorization header:

```http
Authorization: Bearer mira_live_…
```

Keep it in a backend secret manager. Never send it to a browser or mobile application and never include it in logs or support screenshots. Create a replacement key before rotating a running integration, deploy the replacement, then revoke the old key.

Expired or revoked keys receive `401`; a valid key missing the required scope receives `403`. Invalid keys are not included in billable usage.
