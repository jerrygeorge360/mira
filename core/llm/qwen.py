"""Qwen LLM client for MIRA.

Thin wrapper around the DashScope Qwen chat-completion API. Provides plain
text completion and tool-augmented completion used across the agent loop and
the slow-path memory workers.

ISSUE-002: Qwen LLM client.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


class QwenClient:
    """Client for the Qwen chat-completion API (DashScope)."""

    def __init__(self, api_key: str, model: str = "qwen-max") -> None:
        """Initialise the client.

        Args:
            api_key: DashScope API key used to authenticate requests.
            model: Qwen model identifier to target.
        """
        raise NotImplementedError

    def complete(self, messages: Sequence[dict[str, str]]) -> str:
        """Generate a completion for a chat message sequence.

        Args:
            messages: Ordered chat messages, each with ``role`` and ``content``.

        Returns:
            The assistant's generated text.
        """
        raise NotImplementedError

    def complete_with_tools(
        self,
        messages: Sequence[dict[str, str]],
        tools: Sequence[dict[str, Any]],
    ) -> dict[str, Any]:
        """Generate a completion that may request a tool/function call.

        Args:
            messages: Ordered chat messages, each with ``role`` and ``content``.
            tools: Tool/function schemas the model may invoke.

        Returns:
            The raw response payload, including any requested tool calls.
        """
        raise NotImplementedError
