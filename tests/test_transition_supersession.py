"""Verify explicit "from X to Y" transition clause-splitting into supersession pairs.

Ownership: MIRA contributors.
Related issue: ISSUE-027.
Architecture area: slow path.

A single transition sentence ("I switched from MongoDB to PostgreSQL") is split into a
prior and a current atomic fact and flagged directly as a SUPERSEDED_BY pair, since the
sentence states the direction. Non-transition text is untouched.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from core.db.repositories import (
    configure_database,
    create_session,
    repository_connection,
    save_observation,
)
from core.memory.atomic_fact import detect_transitions
from core.memory.graph import find_edges_by_type
from core.memory.slow_path import _apply_transition_supersessions


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    """Configure transition tests to use an isolated database."""
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


@pytest.mark.parametrize(
    ("text", "prior", "current"),
    [
        ("I switched from MongoDB to PostgreSQL for storage.", "MongoDB", "PostgreSQL"),
        ("We migrated from REST to GraphQL.", "REST", "GraphQL"),
        ("I moved from Heroku to AWS because of cost.", "Heroku", "AWS"),
        ("I changed from npm to pnpm.", "npm", "pnpm"),
        ("I replaced Redux with Zustand for state.", "Redux", "Zustand"),
        ("I used to use Vim, now I use VSCode.", "Vim", "VSCode"),
    ],
)
def test_detect_transitions_extracts_prior_and_current(text: str, prior: str, current: str) -> None:
    """Each explicit transition phrasing yields one prior/current value pair."""
    transitions = detect_transitions(text)

    assert len(transitions) == 1
    assert transitions[0]["prior_object"] == prior
    assert transitions[0]["current_object"] == current


def test_detect_transition_with_named_layer_between_verb_and_values() -> None:
    transitions = detect_transitions("I moved my caching layer from Redis to Memcached last month.")

    assert transitions == [
        {
            "subject": "user",
            "predicate": "uses",
            "prior_object": "Redis",
            "current_object": "Memcached",
        }
    ]


@pytest.mark.parametrize(
    "text",
    [
        "I really like PostgreSQL.",
        "I use PostgreSQL for storage.",
        "What database do I use now?",
        "",
    ],
)
def test_non_transition_text_is_ignored(text: str) -> None:
    """Text without explicit transition language produces no pairs."""
    assert detect_transitions(text) == []


def test_transition_creates_directed_supersession_with_evidence(database_path: Path) -> None:
    """A migration sentence yields a superseded prior fact, active current fact, and edge."""
    session_id = create_session("jerry")
    content = "I switched from MongoDB to PostgreSQL for storage."
    observation_id = save_observation(session_id, "user", content)

    edge_ids = _apply_transition_supersessions(observation_id, content)

    assert len(edge_ids) == 1
    edges = find_edges_by_type("SUPERSEDED_BY")
    assert len(edges) == 1
    assert edges[0]["source_observations"] == [observation_id]

    with repository_connection() as connection:
        facts = {
            str(row["object"]): str(row["status"])
            for row in connection.execute(
                "SELECT object, status FROM atomic_facts ORDER BY created_at"
            )
        }
    assert facts == {"MongoDB": "superseded", "PostgreSQL": "active"}


def test_transition_supersession_is_idempotent(database_path: Path) -> None:
    """Re-running the step for the same observation does not duplicate the edge."""
    session_id = create_session("jerry")
    content = "I migrated from MySQL to Postgres."
    observation_id = save_observation(session_id, "user", content)

    first = _apply_transition_supersessions(observation_id, content)
    second = _apply_transition_supersessions(observation_id, content)

    assert len(first) == 1
    assert second == []
    assert len(find_edges_by_type("SUPERSEDED_BY")) == 1
