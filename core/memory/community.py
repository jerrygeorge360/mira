"""Graph-derived community detection and summaries for Deep Mode.

Ownership: Jerry.
Related issue: ISSUE-032.
Architecture area: slow path.

Community summaries are not recursive transcript summaries; they are
graph-derived warm memory used for pattern-level retrieval. Detection runs in the
background over the single typed graph, each community is summarized by the model
into a title plus a concise summary linked to its member nodes, and the summary
is persisted in SQLite and indexed in ChromaDB. Deep Mode later reads these
cached summaries -- no live community detection runs during answer generation.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re

from core.db import chroma
from core.db.repositories import create_community_summary as create_community_summary_record
from core.db.repositories import repository_connection
from core.llm.prompts import render_prompt
from core.llm.qwen import call_qwen_json

Community = dict[str, object]
CommunitySummary = dict[str, object]

LOGGER = logging.getLogger(__name__)

MIN_COMMUNITY_SIZE = 2
EMBEDDING_DIMENSIONS = 8
INDEX_COLLECTION = "community_summaries"

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_'-]+")
STOPWORDS = frozenset({"a", "an", "the", "is", "are", "of", "to", "and", "for", "in", "on"})


def detect_graph_communities() -> list[Community]:
    """Detect communities over active typed-graph edges (background work)."""
    parent: dict[str, str] = {}
    for source_node_id, target_node_id in _active_edges():
        _union(parent, source_node_id, target_node_id)

    groups: dict[str, list[str]] = {}
    for node_id in parent:
        groups.setdefault(_find(parent, node_id), []).append(node_id)

    communities: list[Community] = []
    for member_node_ids in groups.values():
        if len(member_node_ids) < MIN_COMMUNITY_SIZE:
            continue
        members = sorted(member_node_ids)
        communities.append({"community_id": _community_id(members), "member_node_ids": members})
    communities.sort(key=lambda community: str(community["community_id"]))
    return communities


def summarize_community(community_id: str, member_node_ids: list[str]) -> CommunitySummary:
    """Summarize one community into a title and concise graph-derived summary."""
    if not community_id:
        raise ValueError("community_id must not be empty")
    if not member_node_ids:
        raise ValueError("member_node_ids must not be empty")

    nodes = _fetch_nodes(member_node_ids)
    if not nodes:
        raise ValueError("no member nodes found for community")

    prompt = render_prompt(
        "community_summary_generation",
        {"community_nodes": _format_nodes(nodes)},
    )
    response = call_qwen_json(
        [{"role": "user", "content": prompt}],
        schema_name="community_summary_generation",
    )
    payload = response.get("json", {})
    title = _string(payload.get("title")) if isinstance(payload, dict) else ""
    summary_text = _string(payload.get("summary")) if isinstance(payload, dict) else ""
    if not title or not summary_text:
        raise ValueError("community summary requires a title and summary")

    return {
        "community_id": community_id,
        "title": title,
        "summary": summary_text,
        "member_node_ids": [str(node["id"]) for node in nodes],
    }


def store_community_summary(summary: CommunitySummary) -> str:
    """Persist a community summary in SQLite and index it in ChromaDB."""
    community_id = _string(summary.get("community_id"))
    title = _string(summary.get("title"))
    summary_text = _string(summary.get("summary"))
    member_node_ids = _string_list(summary.get("member_node_ids"))
    if not community_id:
        raise ValueError("summary must include community_id")
    if not title or not summary_text:
        raise ValueError("summary must include a title and summary")
    if not member_node_ids:
        raise ValueError("summary must link to at least one member node")

    summary_id = create_community_summary_record(
        {
            "community_id": community_id,
            "title": title,
            "summary": summary_text,
            "member_nodes_json": member_node_ids,
        }
    )
    _index_summary(summary_id, title, summary_text, community_id, member_node_ids)
    LOGGER.info("Stored community summary %s with %d members", summary_id, len(member_node_ids))
    return summary_id


def mark_community_summary_stale(summary_id: str) -> None:
    """Mark a community summary stale for later regeneration (see ISSUE-046)."""
    raise NotImplementedError


def _index_summary(
    summary_id: str,
    title: str,
    summary_text: str,
    community_id: str,
    member_node_ids: list[str],
) -> None:
    embedding = _embed_text(f"{title} {summary_text}")
    chroma.add_embedding(
        INDEX_COLLECTION,
        INDEX_COLLECTION,
        summary_id,
        embedding,
        metadata={"community_id": community_id, "member_count": len(member_node_ids)},
    )


def _active_edges() -> list[tuple[str, str]]:
    with repository_connection() as connection:
        rows = connection.execute(
            """
            SELECT source_node_id, target_node_id
            FROM graph_edges
            WHERE invalidated_at IS NULL
            ORDER BY created_at ASC
            """
        ).fetchall()
    return [(str(row["source_node_id"]), str(row["target_node_id"])) for row in rows]


def _fetch_nodes(member_node_ids: list[str]) -> list[dict[str, object]]:
    unique_ids = sorted(dict.fromkeys(member_node_ids))
    if not unique_ids:
        return []
    placeholders = ", ".join("?" for _ in unique_ids)
    with repository_connection() as connection:
        rows = connection.execute(
            f"SELECT id, node_type, label FROM graph_nodes WHERE id IN ({placeholders})",  # nosec B608
            tuple(unique_ids),
        ).fetchall()
    nodes = [dict(row) for row in rows]
    nodes.sort(key=lambda node: str(node["id"]))
    return nodes


def _format_nodes(nodes: list[dict[str, object]]) -> str:
    return "\n".join(
        f"- {node['id']} ({node.get('node_type', 'node')}): {node['label']}" for node in nodes
    )


def _community_id(member_node_ids: list[str]) -> str:
    digest = hashlib.sha256("|".join(sorted(member_node_ids)).encode("utf-8")).hexdigest()
    return f"community_{digest[:12]}"


def _embed_text(text: str) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSIONS
    for token in _tokens(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        vector[digest[0] % EMBEDDING_DIMENSIONS] += 1.0
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return [1.0, *([0.0] * (EMBEDDING_DIMENSIONS - 1))]
    return [value / norm for value in vector]


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in TOKEN_PATTERN.findall(value.casefold())
        if len(token) > 1 and token not in STOPWORDS
    }


def _find(parent: dict[str, str], node_id: str) -> str:
    parent.setdefault(node_id, node_id)
    root = node_id
    while parent[root] != root:
        root = parent[root]
    while parent[node_id] != root:
        parent[node_id], node_id = root, parent[node_id]
    return root


def _union(parent: dict[str, str], left: str, right: str) -> None:
    left_root = _find(parent, left)
    right_root = _find(parent, right)
    if left_root == right_root:
        return
    # Deterministic: the smaller identifier becomes the shared root.
    high, low = max(left_root, right_root), min(left_root, right_root)
    parent[high] = low


def _string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]
