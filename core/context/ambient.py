"""Sensa-style ambient context provider contract for temporal and optional signals.

Ownership: Jerry.
Related issue: ISSUE-404.
Architecture area: context.
"""


def get_ambient_context(
    timezone_name: str,
    previous_session_at: str | None = None,
    include_optional_signals: bool = False,
) -> dict[str, object]:
    """Provide date, time, timezone, session gap, and optional ambient signals."""
    raise NotImplementedError
