"""Slack bot front-end for MIRA.

Listens for Slack events (mentions and direct messages), forwards them to the
agent, and posts responses back to the originating channel or thread.

ISSUE-018: Slack bot.
"""

from __future__ import annotations


class SlackBot:
    """Event-driven Slack front-end for the MIRA agent."""

    def __init__(self, bot_token: str, app_token: str) -> None:
        """Initialise the bot with its Slack credentials.

        Args:
            bot_token: Slack bot (xoxb) token used to call the Web API.
            app_token: Slack app-level (xapp) token used for Socket Mode.
        """
        raise NotImplementedError

    async def start(self) -> None:
        """Connect to Slack and begin processing incoming events."""
        raise NotImplementedError

    async def handle_message(self, channel: str, text: str) -> None:
        """Handle an inbound message and reply with the agent's response.

        Args:
            channel: Identifier of the channel or DM the message arrived on.
            text: The message text from the user.
        """
        raise NotImplementedError
