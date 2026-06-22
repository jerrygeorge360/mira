"""Final prompt assembly contract across all context sources.

Ownership: Jerry.
Related issue: ISSUE-401.
Architecture area: context.
"""


def build_prompt(
    user_message: str,
    recent_turns: list[str],
    session_items: list[dict[str, object]],
    retrieved_memories: list[dict[str, object]],
    ambient_context: dict[str, object],
    token_budget: int,
) -> str:
    """Build the final model prompt under the configured context budget."""
    raise NotImplementedError
