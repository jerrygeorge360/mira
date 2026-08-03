# ADR-0017: Provider-Reported LLM Usage and Optional Compression Gateway

## Status

Accepted.

## Context

MIRA uses several model calls during one user-visible turn: purpose classification, routing or
sufficiency checks, answer generation, and later slow-path extraction. Prompt-size estimates are
useful for budgeting but cannot prove billed consumption across providers. A compression proxy
also needs to be compared against an unchanged baseline without becoming a second model-provider
configuration or silently changing MIRA's memory behavior.

Paritok compresses tool output and older conversation history. MIRA previously supplied selected
memory inside one latest user message, which offered no safe older-history boundary to compress.

## Decision

1. Record every model request at the generic OpenAI-compatible client boundary.
2. Group requests by a workspace-scoped logical agent or worker run.
3. Treat provider-reported input/output usage as authoritative. Store fallback estimates under a
   separate `usage_source` and never use them as evidence of measured savings.
4. Store metadata and a SHA-256 fingerprint of the exact messages, not prompt or response content.
5. Keep provider selection and gateway selection independent. The supported gateways are
   `direct` and `paritok`.
6. Reject a Paritok request when its configured upstream profile differs from MIRA's active
   provider.
7. Preserve the final task turn. Put selected MIRA context in a preceding turn so Paritok can
   compress older context without changing retrieval, correction handling, sufficiency, or answer
   persistence.
8. Compare identical message payloads in paired direct and Paritok calls. Require provider usage
   from both responses and report a case-specific quality check with token reduction.
9. Compute USD estimates only from operator-supplied current rates.
10. Attribute live savings with request-scoped proxy response headers. Do not derive per-user chat
    savings from Paritok's process-wide `/stats` endpoint.

## Consequences

- The admin dashboard can show model consumption by provider and gateway without exposing user
  content.
- The Memory Pipeline read model attributes background model calls and compression savings to the
  source observation; it does not merge asynchronous worker cost into the earlier chat badge.
- Failed calls and structured-output repair attempts are visible as separate provider requests.
- A user-visible answer reports the total model usage of its complete logical run. Paritok turns
  also show measured eligible-context tokens before compression, after compression, and saved.
- The controlled paired report measures answer generation only. It must not be presented as a
  full-pipeline reduction result.
- Paritok remains optional. Existing deployments and non-streaming clients continue to use the
  direct provider path unless an administrator or explicit call selects the proxy.
- Changing the Paritok upstream provider requires proxy reconfiguration and restart.
- The pinned Paritok 1.2.7 image carries three narrow compatibility patches. Its OpenAI handler
  computes compressed history but does not assign the returned messages, and its history path does
  not add those token counts to `/stats`. It also exposes only process-wide savings, so MIRA adds
  response headers for request attribution. The Docker build asserts the exact upstream source
  before applying each patch; remove them after the upstream package includes the corrections.
