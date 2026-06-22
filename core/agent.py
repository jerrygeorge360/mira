"""Top-level orchestration contract for session-aware MIRA turns.

Ownership: Jerry.
Related issue: ISSUE-001.
Architecture area: context.
"""


class Agent:
    """Coordinate observation, session continuity, retrieval, prompting, and generation."""

    def __init__(self, session_id: str) -> None:
        """Create an agent contract for a conversation session."""
        raise NotImplementedError

    def handle_turn(self, user_message: str) -> str:
        """Accept one user turn and return the eventual model response."""
        raise NotImplementedError

    def reset_session(self) -> None:
        """Reset temporary session state without deleting durable memory."""
        raise NotImplementedError
