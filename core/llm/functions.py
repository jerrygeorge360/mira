"""Function-calling schema helpers for MIRA.

Builds and validates the JSON tool schemas exposed to the Qwen client, and
dispatches model-requested calls to the registered Python callables.

ISSUE-003: LLM function calling.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def build_tool_schema(func: Callable[..., Any]) -> dict[str, Any]:
    """Derive a JSON tool schema from a typed Python callable.

    Args:
        func: The callable to expose as a model-invokable tool.

    Returns:
        A JSON-serialisable tool schema describing the callable.
    """
    raise NotImplementedError


def dispatch_tool_call(
    name: str,
    arguments: dict[str, Any],
    registry: dict[str, Callable[..., Any]],
) -> Any:
    """Invoke a registered callable for a model-requested tool call.

    Args:
        name: The name of the tool the model asked to call.
        arguments: Decoded keyword arguments for the call.
        registry: Mapping of tool names to their Python implementations.

    Returns:
        The return value of the invoked callable.
    """
    raise NotImplementedError
