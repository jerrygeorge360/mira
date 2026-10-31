# Coolify deployment on Contabo

MIRA's Coolify application uses `docker-compose.coolify.yml` from this repository.
The stack contains the API, background worker, MCP server, frontend, and an
internal HTTP gateway. Coolify's proxy terminates TLS and routes `mira.ninja`
and `www.mira.ninja` to the gateway on port 80. Do not publish container ports
80 or 443 on the host; they belong to Coolify's proxy.

## Configuration

In the MIRA production application in Coolify, use the public Git source and
the Compose file `/docker-compose.coolify.yml`. The current deployment branch
is `deploy/coolify-contabo` until the changes are merged into `main`.

Configure these Compose variables in Coolify before deployment:

| Variable | Purpose |
| --- | --- |
| `LLM_PROFILE` | Model provider profile; defaults to `dashscope`. |
| `LLM_API_KEY` | API credential for the selected model provider. |
| `GITHUB_CLIENT_ID` | Existing MIRA GitHub OAuth application's client ID. |
| `GITHUB_CLIENT_SECRET` | Its client secret. |
| `MIRA_MCP_API_KEY` | A newly generated long random bearer token for legacy MCP clients. |

The GitHub OAuth application's callback URL must be
`https://mira.ninja/api/auth/github/callback`. The Compose file fixes the public
URLs, secure cookies, GitHub authentication, and local FastEmbed embeddings.
Do not put credentials into Git or the Compose file.

The SQLite database is the source of truth and lives in the `mira-sqlite` Docker
volume. `mira-chroma` stores a rebuildable vector index, and
`mira-model-cache` stores the embedding model. Restore an old SQLite backup
**before** accepting user traffic if retaining existing accounts and memory is
required. Docker volumes are not backups; arrange an off-server SQLite backup.

## Domain cutover

The prior CineBridge staging deployment had temporary `mira.ninja` and
`api.mira.ninja` routes. It retains its own `cinebridge.mira.ninja` and
`api.cinebridge.mira.ninja` routes. In Name.com, point the apex A record to
the Contabo server public IPv4 address and make `www` a CNAME for `mira.ninja`
(or an A record to the same IPv4 address). Preserve the CineBridge subdomain
records. Remove stale AAAA records if the server has no public IPv6 address.

After DNS resolves, verify `https://mira.ninja/`,
`https://mira.ninja/api/health`, GitHub sign-in, one chat turn, and the worker's
memory processing. The old Alibaba ECS deployment workflow is manual only;
Coolify should handle future deployments from the chosen branch.
