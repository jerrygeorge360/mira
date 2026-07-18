# ADR-0014 - Provenance-Aware Conversation Deletion

## Status

Accepted

## Context

A conversation can produce observations, facts, graph edges, entities, reflections, communities,
foresight, vectors, and working-memory records. Deleting only the chat transcript leaves MIRA able
to recall information the user expected to remove. Deleting every related conclusion immediately
is also incorrect when another retained conversation independently supports it.

## Decision

Deleting a conversation retracts that conversation from memory provenance and then evaluates the
remaining support for each derived artifact. The session is tombstoned and its observation content
is scrubbed so foreign-key and trace integrity remain intact. Its vectors are removed and pending
slow-path work is quarantined.

Facts and foresight sourced only from the deleted session are deactivated. Reflection and graph-edge
provenance is pruned; records without remaining evidence are made stale or invalidated. Unsupported
graph nodes, orphaned entities, community summaries, and working-memory records are then removed or
expired. If the final active session is deleted, MIRA resets the workspace memory so no unsupported
derived state survives.

## Consequences

Deleting one conversation preserves memory that still has valid evidence elsewhere while preventing
unsupported recall from the deleted source. Provenance becomes part of deletion correctness, so new
derived-memory types must expose their evidence links and participate in invalidation. Tombstoned
observations remain as non-retrievable structural records rather than disappearing physically.
