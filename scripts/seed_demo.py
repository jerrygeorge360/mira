"""Deterministic demo-data seeding for MIRA.

Ownership: Sarah.
Related issue: ISSUE-049.
Architecture area: demo.

Seeds a self-contained demo so every feature is visible without waiting for an
organic long conversation: sessions, observations, Session Working Set examples
(including a 2025->2026 correction), a Python/Rust contradiction, a
MongoDB->PostgreSQL supersession, a hackathon-deadline foresight, reflections,
community summaries, typed graph edges, and retrieval/prompt/answer-trace logs.

The seed is idempotent: it is keyed by a fixed demo-session title and skips if
already present. Pass ``reset=True`` (CLI ``--reset``) to rebuild from scratch.
No secrets are hardcoded; the database path comes from the argument or
``MIRA_DB_PATH`` (default ``./mira.db``).
"""

from __future__ import annotations

import argparse
import os

from core.db.repositories import (
    configure_database,
    create_answer_trace,
    create_atomic_fact,
    create_community_summary,
    create_prompt_log,
    create_retrieval_log,
    create_session,
    repository_connection,
    save_observation,
)
from core.memory.foresight import create_foresight
from core.memory.graph import canonicalize_entity, create_graph_edge, create_graph_node
from core.memory.reflection import store_reflection_with_evidence
from core.session.working_set import upsert_session_item

DEMO_USER = "demo-user"
DEMO_TITLE = "MIRA Demo"
DEMO_COMMUNITY_PREFIX = "demo_"
DEFAULT_DB_PATH = os.environ.get("MIRA_DB_PATH", "./mira.db")


def seed_demo_data(database_path: str = DEFAULT_DB_PATH, reset: bool = False) -> dict[str, object]:
    """Seed deterministic demo data and return a summary of what was created."""
    configure_database(database_path)

    existing = _find_demo_session()
    if existing is not None:
        if not reset:
            return {"status": "already_seeded", "session_id": existing}
        _reset_demo(existing)

    session_id = create_session(DEMO_USER, DEMO_TITLE)
    observations = _seed_observations(session_id)
    nodes: dict[str, str] = {}

    _seed_session_working_set(session_id, observations)
    contradiction_edges = _seed_contradiction(observations, nodes)
    supersession_edges = _seed_supersession(observations, nodes)
    _seed_mentions(observations, nodes)
    foresight_id = _seed_foresight(observations)
    reflection_ids = _seed_reflections(observations)
    community_id = _seed_community(observations, nodes)
    _seed_logs(session_id, observations)

    return {
        "status": "seeded",
        "session_id": session_id,
        "observations": len(observations),
        "graph_edges": contradiction_edges + supersession_edges,
        "foresight_id": foresight_id,
        "reflections": len(reflection_ids),
        "community_id": community_id,
    }


def main() -> None:
    """CLI entry point: ``python -m scripts.seed_demo [--db PATH] [--reset]``."""
    parser = argparse.ArgumentParser(description="Seed deterministic MIRA demo data.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="SQLite database path.")
    parser.add_argument("--reset", action="store_true", help="Rebuild demo data from scratch.")
    args = parser.parse_args()
    summary = seed_demo_data(args.db, reset=args.reset)
    print(f"Demo seed {summary['status']}: session {summary['session_id']}")


def _seed_observations(session_id: str) -> dict[str, str]:
    turns = {
        "correction_user": ("user", "Use 2026, not 2025, for all dates."),
        "correction_assistant": ("assistant", "Understood — I'll use 2026 going forward."),
        "python": ("user", "I prefer Python for the backend."),
        "rust": ("user", "Actually, I prefer Rust now."),
        "migration": ("user", "I switched from MongoDB to PostgreSQL for storage."),
        "hackathon": ("user", "The hackathon submission is due 2026-07-01."),
        "tiers": ("user", "Keep MIRA session memory separate from durable tiers."),
    }
    return {
        key: save_observation(session_id, role, content) for key, (role, content) in turns.items()
    }


def _seed_session_working_set(session_id: str, observations: dict[str, str]) -> None:
    items = [
        {
            "type": "correction",
            "content": "Use 2026, not 2025, for all dates.",
            "scope": "project",
            "status": "provisional",
            "priority": 0.96,
            "explicitness_label": "direct_correction",
            "evidence_span": "Use 2026, not 2025.",
            "origin": "micro_path",
            "source_observations": [observations["correction_user"]],
        },
        {
            "type": "active_constraint",
            "content": "Keep MIRA session memory separate from durable tiers.",
            "scope": "project",
            "status": "hydrated",
            "priority": 0.82,
            "explicitness_label": "direct_instruction",
            "evidence_span": "session memory separate from durable tiers",
            "origin": "cross_session_hydration",
            "source_observations": [observations["tiers"]],
        },
        {
            "type": "decision",
            "content": "Store MIRA context in MongoDB.",
            "scope": "project",
            "status": "rejected",
            "priority": 0.4,
            "explicitness_label": "direct_decision",
            "evidence_span": "Store MIRA context in MongoDB.",
            "origin": "micro_path",
            "source_observations": [observations["migration"]],
            "resolution_reason": "Superseded by the PostgreSQL migration.",
        },
    ]
    for item in items:
        upsert_session_item(session_id, item)


def _seed_contradiction(observations: dict[str, str], nodes: dict[str, str]) -> int:
    create_atomic_fact(
        {
            "subject": "Jerry",
            "predicate": "PREFERS",
            "object": "Python",
            "confidence": 0.6,
            "status": "contradicted",
            "source_observation_id": observations["python"],
        }
    )
    create_atomic_fact(
        {
            "subject": "Jerry",
            "predicate": "PREFERS",
            "object": "Rust",
            "confidence": 0.9,
            "status": "active",
            "source_observation_id": observations["rust"],
        }
    )
    python_node = _entity_node("Python", nodes)
    rust_node = _entity_node("Rust", nodes)
    create_graph_edge(python_node, rust_node, "CONTRADICTS", 0.85, [observations["rust"]])
    return 1


def _seed_supersession(observations: dict[str, str], nodes: dict[str, str]) -> int:
    create_atomic_fact(
        {
            "subject": "Jerry",
            "predicate": "WORKS_ON",
            "object": "MongoDB",
            "confidence": 0.6,
            "status": "superseded",
            "source_observation_id": observations["migration"],
        }
    )
    create_atomic_fact(
        {
            "subject": "Jerry",
            "predicate": "WORKS_ON",
            "object": "PostgreSQL",
            "confidence": 0.95,
            "status": "active",
            "source_observation_id": observations["migration"],
        }
    )
    mongo_node = _entity_node("MongoDB", nodes)
    postgres_node = _entity_node("PostgreSQL", nodes)
    create_graph_edge(mongo_node, postgres_node, "SUPERSEDED_BY", 0.95, [observations["migration"]])
    return 1


def _seed_mentions(observations: dict[str, str], nodes: dict[str, str]) -> None:
    mira_node = _entity_node("MIRA", nodes)
    postgres_node = _entity_node("PostgreSQL", nodes)
    migration_node = _observation_node(observations["migration"], "switched to PostgreSQL")
    create_graph_edge(mira_node, postgres_node, "WORKS_ON", 0.9, [observations["migration"]])
    create_graph_edge(migration_node, postgres_node, "MENTIONS", 1.0, [observations["migration"]])


def _seed_foresight(observations: dict[str, str]) -> str:
    return create_foresight(
        {
            "content": "Hackathon submission is due 2026-07-01.",
            "reason": "User stated the deadline.",
            "status": "active",
            "source_observation_id": observations["hackathon"],
            "valid_from": "2026-06-24T00:00:00+00:00",
            "valid_until": "2026-07-01T23:59:59+00:00",
            "always_inject": False,
        }
    )


def _seed_reflections(observations: dict[str, str]) -> list[str]:
    reflections = [
        (
            {
                "reflection_type": "self_knowledge",
                "content": "MIRA keeps session memory separate from durable tiers.",
                "confidence": 0.85,
            },
            [observations["tiers"]],
        ),
        (
            {
                "reflection_type": "user_knowledge",
                "content": "Jerry now prefers Rust over Python for the backend.",
                "confidence": 0.82,
            },
            [observations["rust"]],
        ),
    ]
    return [
        store_reflection_with_evidence(reflection, evidence) for reflection, evidence in reflections
    ]


def _seed_community(observations: dict[str, str], nodes: dict[str, str]) -> str:
    postgres_node = _entity_node("PostgreSQL", nodes)
    mongo_node = _entity_node("MongoDB", nodes)
    community_summary_id = create_community_summary(
        {
            "community_id": f"{DEMO_COMMUNITY_PREFIX}persistence",
            "title": "Persistence Architecture",
            "summary": "SQLite is the source of truth; ChromaDB indexes stay rebuildable.",
            "member_nodes_json": [postgres_node, mongo_node],
        }
    )
    community_node = create_graph_node(
        node_type="community",
        label="Persistence Architecture",
        source_table="community_summaries",
        source_id=community_summary_id,
    )
    evidence = [observations["migration"]]
    create_graph_edge(postgres_node, community_node, "PART_OF_COMMUNITY", 0.7, evidence)
    create_graph_edge(mongo_node, community_node, "PART_OF_COMMUNITY", 0.7, evidence)
    return community_summary_id


def _seed_logs(session_id: str, observations: dict[str, str]) -> None:
    create_retrieval_log(
        {
            "session_id": session_id,
            "query": "What database do I use now?",
            "retrieval_mode": "relational",
            "retrieved_records_json": [{"source": "atomic_facts", "id": "demo_postgres_fact"}],
        }
    )
    create_prompt_log(
        {
            "session_id": session_id,
            "user_observation_id": observations["migration"],
            "included_session_items_json": [],
            "included_memory_items_json": [],
            "included_recent_turns_json": [observations["python"], observations["rust"]],
            "token_budget_json": {"prompt_tokens": 512, "budget": 4000},
        }
    )
    create_answer_trace(
        {
            "session_id": session_id,
            "user_observation_id": observations["migration"],
            "assistant_observation_id": observations["correction_assistant"],
            "retrieval_mode": "relational",
            "retrieved_observation_ids_json": [observations["python"], observations["rust"]],
            "retrieved_fact_ids_json": [],
            "session_item_ids_json": [],
            "hot_memory_ids_json": [],
            "graph_path_ids_json": [],
            "community_summary_ids_json": [],
            "sufficiency_json": {"is_sufficient": True, "missing": [], "rewrite_query": None},
            "prompt_sections_json": [
                {"section": "session_working_set", "source_ids": []},
                {"section": "retrieved", "source_ids": [observations["rust"]]},
            ],
            "hydration_ids_json": [],
        }
    )


def _entity_node(name: str, nodes: dict[str, str]) -> str:
    if name in nodes:
        return nodes[name]
    entity_id = canonicalize_entity(name)
    node_id = create_graph_node(
        node_type="entity", label=name, source_table="entities", source_id=entity_id
    )
    nodes[name] = node_id
    return node_id


def _observation_node(observation_id: str, label: str) -> str:
    return create_graph_node(
        node_type="observation",
        label=label,
        source_table="observations",
        source_id=observation_id,
    )


def _find_demo_session() -> str | None:
    with repository_connection() as connection:
        row = connection.execute(
            "SELECT id FROM sessions WHERE title = ? ORDER BY created_at ASC LIMIT 1",
            (DEMO_TITLE,),
        ).fetchone()
    return None if row is None else str(row["id"])


def _reset_demo(session_id: str) -> None:
    with repository_connection() as connection:
        observation_ids = [
            str(row["id"])
            for row in connection.execute(
                "SELECT id FROM observations WHERE session_id = ?", (session_id,)
            ).fetchall()
        ]
        reflection_ids = (
            [
                str(row["reflection_id"])
                for row in connection.execute(
                    "SELECT DISTINCT reflection_id FROM reflection_evidence "
                    f"WHERE observation_id IN ({_placeholders(observation_ids)})",  # noqa: S608
                    tuple(observation_ids),
                ).fetchall()
            ]
            if observation_ids
            else []
        )

        demo_source_ids = set(observation_ids) | set(reflection_ids)
        node_ids = [
            str(row["id"])
            for row in connection.execute("SELECT id, source_id FROM graph_nodes").fetchall()
            if str(row["source_id"]) in demo_source_ids
            or str(row["source_id"]).startswith(DEMO_COMMUNITY_PREFIX)
        ]
        for node_id in node_ids:
            connection.execute(
                "DELETE FROM graph_edges WHERE source_node_id = ? OR target_node_id = ?",
                (node_id, node_id),
            )
        if node_ids:
            connection.execute(
                f"DELETE FROM graph_nodes WHERE id IN ({_placeholders(node_ids)})",  # noqa: S608
                tuple(node_ids),
            )

        if reflection_ids:
            placeholders = _placeholders(reflection_ids)
            connection.execute(
                f"DELETE FROM reflection_evidence WHERE reflection_id IN ({placeholders})",  # noqa: S608
                tuple(reflection_ids),
            )
            connection.execute(
                f"DELETE FROM reflections WHERE id IN ({placeholders})",  # noqa: S608
                tuple(reflection_ids),
            )
        if observation_ids:
            placeholders = _placeholders(observation_ids)
            for table, column in (
                ("atomic_facts", "source_observation_id"),
                ("foresight_records", "source_observation_id"),
                ("slow_path_queue", "observation_id"),
            ):
                connection.execute(
                    f"DELETE FROM {table} WHERE {column} IN ({placeholders})",  # noqa: S608
                    tuple(observation_ids),
                )
        connection.execute(
            "DELETE FROM community_summaries WHERE community_id LIKE ?",
            (f"{DEMO_COMMUNITY_PREFIX}%",),
        )
        for table in ("session_working_set", "retrieval_logs", "prompt_logs", "answer_traces"):
            connection.execute(f"DELETE FROM {table} WHERE session_id = ?", (session_id,))  # noqa: S608
        connection.execute("DELETE FROM observations WHERE session_id = ?", (session_id,))
        connection.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


def _placeholders(values: list[str]) -> str:
    return ", ".join("?" for _ in values)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
