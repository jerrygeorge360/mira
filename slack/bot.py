"""Slack bot lifecycle and event-handling contracts.

Ownership: Kelechi.
Related issue: ISSUE-701.
Architecture area: Slack.
"""


def run_bot() -> None:
    """Run the future Slack bot integration."""
    raise NotImplementedError


def handle_message(channel_id: str, user_id: str, text: str) -> str:
    """Handle one future Slack message event."""
    raise NotImplementedError
