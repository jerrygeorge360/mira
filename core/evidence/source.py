"""Resolve original evidence content with workspace and lifecycle checks."""

from __future__ import annotations

import sqlite3

from core.db.repositories import repository_connection


def resolve_source(
    evidence_source_id: str, *, workspace_id: str, connection: sqlite3.Connection | None = None
) -> dict[str, object]:
    """Return content and provenance of a live source, or reject inaccessible records."""
    owned = connection is None
    db = connection or repository_connection()
    try:
        db.row_factory = sqlite3.Row
        source = db.execute(
            "SELECT * FROM evidence_sources WHERE id = ? AND workspace_id = ? "
            "AND retracted_at IS NULL",
            (evidence_source_id, workspace_id),
        ).fetchone()
        if source is None:
            raise ValueError("active evidence source not found in workspace")
        if source["source_type"] == "conversation_observation":
            row = db.execute(
                "SELECT o.content, o.created_at, o.session_id, s.status AS session_status "
                "FROM observations AS o JOIN sessions AS s ON s.id = o.session_id "
                "AND s.workspace_id = o.workspace_id "
                "WHERE o.id = ? AND o.workspace_id = ?",
                (source["source_id"], workspace_id),
            ).fetchone()
            if row is None or row["session_status"] == "deleted":
                raise ValueError("observation is unavailable")
            provenance = {"session_id": row["session_id"], "created_at": row["created_at"]}
        elif source["source_type"] == "document_chunk":
            row = db.execute(
                "SELECT c.content, c.chunk_index, c.heading, c.page_start, c.page_end, "
                "d.id AS document_id, d.filename, d.status AS document_status, d.deleted_at, "
                "k.status AS knowledge_base_status, k.id AS knowledge_base_id "
                "FROM document_chunks AS c JOIN documents AS d ON d.id = c.document_id "
                "AND d.workspace_id = c.workspace_id AND d.knowledge_base_id = c.knowledge_base_id "
                "JOIN knowledge_bases AS k ON k.id = d.knowledge_base_id "
                "AND k.workspace_id = d.workspace_id "
                "WHERE c.id = ? AND c.workspace_id = ?",
                (source["source_id"], workspace_id),
            ).fetchone()
            if (
                row is None
                or row["document_status"] != "ready"
                or row["deleted_at"] is not None
                or row["knowledge_base_status"] != "active"
                or source["knowledge_base_id"] != row["knowledge_base_id"]
            ):
                raise ValueError("document chunk is unavailable")
            provenance = {
                key: row[key]
                for key in (
                    "document_id",
                    "filename",
                    "knowledge_base_id",
                    "chunk_index",
                    "heading",
                    "page_start",
                    "page_end",
                )
            }
        else:
            raise ValueError("unsupported evidence source type")
        return {
            "id": source["id"],
            "workspace_id": workspace_id,
            "source_type": source["source_type"],
            "source_id": source["source_id"],
            "content": row["content"],
            "content_hash": source["content_hash"],
            "project_id": source["project_id"],
            "namespace": source["namespace"],
            "knowledge_base_id": source["knowledge_base_id"],
            "authority": source["authority"],
            "observed_at": source["observed_at"],
            "provenance": provenance,
        }
    finally:
        if owned:
            db.close()
