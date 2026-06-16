"""Working memory for MIRA.

Holds the bounded, in-session context that the agent reasons over directly: the
recent turns plus the salient facts promoted from long-term memory. Acts as the
buffer between the fast path and the LLM prompt.

ISSUE-006: Working memory.
"""

from __future__ import annotations


class WorkingMemory:
    """Bounded in-session buffer of recent and salient context."""

    def __init__(self, capacity: int = 32) -> None:
        """Initialise working memory with a fixed item capacity.

        Args:
            capacity: Maximum number of items retained before eviction.
        """
        raise NotImplementedError

    def add(self, item: str) -> None:
        """Add an item to working memory, evicting the oldest if at capacity.

        Args:
            item: The context fragment to retain.
        """
        raise NotImplementedError

    def snapshot(self) -> list[str]:
        """Return the current contents in retention order.

        Returns:
            The retained items, oldest first.
        """
        raise NotImplementedError

    def clear(self) -> None:
        """Drop all items from working memory."""
        raise NotImplementedError
