"""Agent orchestration loop for MIRA.

Wires the dual-stream memory subsystem, retrieval router, and LLM client into
a single conversational agent. The agent ingests a user turn, observes it onto
the fast path, retrieves relevant context, generates a response, and schedules
slow-path consolidation.

ISSUE-001: Agent orchestration.
"""

from __future__ import annotations


class Agent:
    """Top-level MIRA agent coordinating memory, retrieval, and generation."""

    def __init__(self, session_id: str) -> None:
        """Initialise the agent for a given conversation session.

        Args:
            session_id: Stable identifier for the conversation this agent serves.
        """
        raise NotImplementedError

    def handle_turn(self, user_message: str) -> str:
        """Process a single user turn and return the agent's reply.

        Args:
            user_message: The raw user utterance for this turn.

        Returns:
            The agent's generated response text.
        """
        raise NotImplementedError

    def reset(self) -> None:
        """Clear transient per-session state without dropping persisted memory."""
        raise NotImplementedError
