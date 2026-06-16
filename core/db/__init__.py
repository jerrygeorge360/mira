"""Database adapters for MIRA.

Owns the persistent stores: the SQLite relational schema for observations,
memories, and the knowledge graph, and the Chroma adapter for embeddings.

See docs/adr/0002-sqlite-over-postgres.md for the relational store choice.

ISSUE-014: Database layer bootstrap.
"""
