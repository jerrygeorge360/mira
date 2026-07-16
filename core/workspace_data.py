"""Workspace-scoped data deletion helpers.

SQLite remains the source of truth. Chroma only stores workspace-tagged pointers,
so a workspace reset removes both durable rows and vector pointers.
"""

from __future__ import annotations

from core.db import chroma
from core.db.repositories import repository_connection

_DELETE_STATEMENTS: tuple[tuple[str, str], ...] = (
    (
        "reflection_evidence",
        """
        DELETE FROM reflection_evidence
        WHERE reflection_id IN (SELECT id FROM reflections WHERE workspace_id = ?)
           OR observation_id IN (SELECT id FROM observations WHERE workspace_id = ?)
        """,
    ),
    ("answer_traces", "DELETE FROM answer_traces WHERE workspace_id = ?"),
    ("prompt_logs", "DELETE FROM prompt_logs WHERE workspace_id = ?"),
    ("retrieval_logs", "DELETE FROM retrieval_logs WHERE workspace_id = ?"),
    ("slow_path_step_journal", "DELETE FROM slow_path_step_journal WHERE workspace_id = ?"),
    ("slow_path_queue", "DELETE FROM slow_path_queue WHERE workspace_id = ?"),
    (
        "session_working_set",
        """
        DELETE FROM session_working_set
        WHERE session_id IN (SELECT id FROM sessions WHERE workspace_id = ?)
        """,
    ),
    ("graph_edges", "DELETE FROM graph_edges WHERE workspace_id = ?"),
    ("community_summaries", "DELETE FROM community_summaries WHERE workspace_id = ?"),
    ("working_memory", "DELETE FROM working_memory WHERE workspace_id = ?"),
    ("foresight_records", "DELETE FROM foresight_records WHERE workspace_id = ?"),
    ("reflections", "DELETE FROM reflections WHERE workspace_id = ?"),
    ("atomic_facts", "DELETE FROM atomic_facts WHERE workspace_id = ?"),
    ("entities", "DELETE FROM entities WHERE workspace_id = ?"),
    ("graph_nodes", "DELETE FROM graph_nodes WHERE workspace_id = ?"),
    ("canonical_subjects", "DELETE FROM canonical_subjects WHERE workspace_id = ?"),
    ("canonical_predicates", "DELETE FROM canonical_predicates WHERE workspace_id = ?"),
    ("observations", "DELETE FROM observations WHERE workspace_id = ?"),
    ("sessions", "DELETE FROM sessions WHERE workspace_id = ?"),
)


def delete_workspace_data(workspace_id: str) -> dict[str, int]:
    """Delete product data for one workspace while preserving auth/account rows."""
    counts: dict[str, int] = {}
    for collection in chroma.SUPPORTED_COLLECTIONS:
        chroma.delete_workspace_vectors(collection, workspace_id=workspace_id)

    with repository_connection() as connection:
        for table, statement in _DELETE_STATEMENTS:
            parameter_count = statement.count("?")
            cursor = connection.execute(statement, (workspace_id,) * parameter_count)
            counts[table] = max(cursor.rowcount, 0)
    return counts
