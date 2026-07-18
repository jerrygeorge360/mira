# ADR-0016 - Authenticated Standalone MCP Service

## Status

Accepted

## Context

MIRA's memory operations need to be available to external agents without coupling the MCP protocol
lifecycle to the browser API or Slack adapter. A public MCP endpoint also needs user authorization
and workspace isolation; accepting a workspace id in tool arguments would not provide either.

## Decision

Expose the transport-independent memory tool registry through a standalone MCP service using the
official SDK's Streamable HTTP transport. The service is stateless at the HTTP layer and shares
MIRA's authoritative persistence with the API and worker. Each request resolves its workspace from
an authenticated bearer token before constructing the tool registry; tool parameters can select
records within that workspace but cannot select ownership.

The FastAPI application acts as MIRA's OAuth 2.1 authorization server for consumer clients. GitHub
authenticates the person, while MIRA issues opaque, resource-bound access and rotating refresh
tokens. Authorization code flows require PKCE. Static token-to-workspace bindings remain available
as an administrative and backward-compatible path.

## Consequences

MCP clients get standard discovery and authorization while core memory operations remain reusable
outside the protocol service. The API and MCP public URLs, issuer metadata, redirect URIs, and proxy
routes must agree in production. The MCP process can be deployed or restarted independently, but it
must use the same database, vector index, and workspace model as the rest of MIRA.
