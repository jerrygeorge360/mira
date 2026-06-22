"""Define the UI contract for explaining retrieval routing and evidence.

Ownership: Sarah.
Related issue: ISSUE-605.
Architecture area: UI.
"""


def render_retrieval_trace(trace: list[dict[str, object]]) -> None:
    """Render a future retrieval trace and its selected evidence."""
    raise NotImplementedError
