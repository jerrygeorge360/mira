# ADR-0004 — Scope-First Routing with Quick, Deep, and Relational Retrieval

## Status

Accepted

## Context

Direct facts, broad synthesis, and relationship questions need distinct retrieval behavior.

## Decision

Quick, Deep, and Relational are the executable retrieval modes. `Auto` is the public request for
automatic routing, not a fourth retrieval algorithm. The automatic router first classifies
`no_retrieval`, `general_knowledge`, `recent_conversation`, `session_memory`, `durable_memory`,
or `mixed`. These scopes are routing metadata, not memory tiers or retrieval modes.

The router returns a traceable decision: `turn_purpose`, `context_scope`, `route`,
`retrieval_mode`, `used_memory`, `reason`, `confidence`, and `needs_sufficiency_check`.
General-knowledge and recent-conversation scopes generate without durable retrieval.
`no_retrieval` handles store-only updates and standalone casual turns before retrieval-mode
selection. Contextual reactions use a bounded `recent_conversation` scope without querying
durable memory. This answer-routing choice does not suppress slow-path extraction from the saved
user observation.

Turn-purpose classification ignores conversational preambles such as "nice, by the way" and
"oh, also" before deciding whether the semantic content is a question, update, correction, or
casual message. This prevents a new personal fact from being answered as though it were only a
reaction to the previous turn. Standalone greetings and closings still terminate without context.
Explicit transitions can name the changed property, as in "I moved my caching layer from Redis to
Memcached." Targetless corrections fail closed, while a temporal amendment such as "it moved to
the following week" is accepted only when bounded recent turns identify a matching scheduled
event.

Session-only questions can use the Session Working Set directly. Only durable and mixed scopes
select Quick, Deep, or Relational. Deterministic guards prevent a model classifier from turning
clear public questions into personal graph searches.

Before an explicit personal-memory question is sent to durable retrieval, the router evaluates
bounded recent user turns with the same requirement-level sufficiency rules used after retrieval.
When those turns directly support every requested attribute, the query stays in
`recent_conversation`. This closes the consistency window between fast-path persistence and
slow-path materialization without pretending that any merely related recent text is sufficient.
Compound questions must have evidence for every requested property; for example, a DNS-provider
record cannot satisfy a separate frontend-hosting requirement merely because both contain the
generic word "provider." Sufficiency contains no domain-specific attribute alias table. Its cheap
path only recognizes literal clause coverage; Qwen receives the query and bounded evidence with
stable IDs to decide semantic entailment. Questions addressed to a conversation participant are
not hard-locked to general knowledge merely because they use a common question prefix. Under
hybrid or accurate routing, ambiguous cases can use the structured scope classifier and the
bounded role-labelled turns. Strong public-definition routes remain general knowledge when they
do not depend on the conversation.

Sufficiency checking wraps every durable or mixed lookup. It is not a mode and permits at most
one rewrite-and-retry. The check evaluates the requested attribute or relationship, not merely
whether retrieval returned a topically similar record. Its final verdict is included in the
answer prompt and trace so unsupported personal details must be reported as unknown rather than
inferred. The deterministic requirement check remains a cheap fallback rather than the final
authority. For grounded answers, a structured semantic verifier always evaluates meaning and may
cite only identifiers from the supplied evidence set. Recent-conversation questions use the same
grounded check before bypassing durable retrieval, preventing plausible world knowledge from being
substituted for an unstated personal reason. Compound evidence is checked as a whole because
topical overlap for one clause is not proof that every clause is answered.

Correction response routing is also separate from durable reconciliation: the fast path updates
the Session Working Set immediately, while the slow path creates durable supersession or
contradiction semantics. A correction such as "that's no longer true" does not identify a target,
so MIRA asks for clarification and prevents that unresolved phrase from becoming an atomic fact.

## Consequences

The public API remains compatible with `retrieval_mode=auto` and projects non-durable routes as
`mode=general`. Internally, however, every executed durable lookup is Quick, Deep, or Relational.
The extra scope decision avoids irrelevant memory retrieval and makes conversational failures
inspectable through the existing answer trace. Requirement-level sufficiency adds a small
deterministic check. Ambiguous semantic or causal cases add one bounded structured model call,
and retrieval still retries at most once. This cost prevents literal vocabulary mismatch and
plausible-but-unstated explanations from controlling the answer.
