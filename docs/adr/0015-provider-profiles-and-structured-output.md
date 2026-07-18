# ADR-0015 - Provider Profiles and Capability-Aware Structured Output

## Status

Accepted

## Context

MIRA uses model calls for both natural-language generation and schema-sensitive memory extraction.
OpenAI-compatible providers share a transport shape but do not all implement the same structured
output modes. In particular, sending `json_schema` to a provider that only supports `json_object`
can fail, while accepting arbitrary text can silently corrupt the memory pipeline.

## Decision

Keep one OpenAI-compatible client boundary and select providers through named profiles. A profile
defines the API-key environment variable, endpoint, default model, response-format capability, and
optional embedding configuration. Explicit generic environment overrides remain available for an
unlisted compatible provider.

Structured extraction always includes the requested schema contract in the prompt and validates the
parsed result locally. The adapter uses `json_schema` when the selected provider supports it and
uses `json_object` for providers such as DeepSeek. Missing keys or invalid values trigger bounded
repair attempts; transport compatibility does not weaken MIRA's local schema validation.

## Consequences

Changing providers does not require changes throughout memory modules, and provider limitations are
handled at the adapter boundary. `json_object` guarantees JSON syntax, not schema conformance, so
local validation and visible worker failures remain mandatory. Supporting a new provider requires a
profile and focused compatibility tests rather than a parallel client implementation.
