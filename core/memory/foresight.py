"""Foresight / anticipatory memory for MIRA.

Projects forward from consolidated memory to anticipate the user's likely next
needs, pre-fetching or pre-computing context so the agent can respond with
relevant information before it is explicitly requested.

ISSUE-008: Foresight.
"""

from __future__ import annotations


def anticipate(session_id: str) -> list[str]:
    """Predict context the user is likely to need next in this session.

    Args:
        session_id: Conversation to generate anticipatory context for.

    Returns:
        Identifiers of memory items predicted to be relevant soon.
    """
    raise NotImplementedError


def prefetch(memory_ids: list[str]) -> None:
    """Warm caches for memory items expected to be needed shortly.

    Args:
        memory_ids: Items to pre-load ahead of an anticipated request.
    """
    raise NotImplementedError
