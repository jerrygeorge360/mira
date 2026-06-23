"""Qwen/DashScope client boundary for model generation calls.

Ownership: Jerry.
Related issue: ISSUE-019.
Architecture area: llm.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

DASHSCOPE_API_KEY_ENV = "DASHSCOPE_API_KEY"
DASHSCOPE_ENDPOINT_ENV = "DASHSCOPE_CHAT_ENDPOINT"
DEFAULT_QWEN_MODEL = "qwen-plus"
DEFAULT_DASHSCOPE_ENDPOINT = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
MAX_ATTEMPTS = 3
RETRY_BACKOFF_S = 0.25

Message = dict[str, str]
ResponseObject = dict[str, object]
Transport = Callable[[str, dict[str, str], dict[str, object], int], dict[str, object]]


class QwenClientError(RuntimeError):
    """Base error for Qwen/DashScope adapter failures."""


class QwenConfigurationError(QwenClientError):
    """Raised when the Qwen/DashScope adapter is not configured."""


class QwenRequestError(QwenClientError):
    """Raised when the Qwen/DashScope request fails."""


class QwenResponseError(QwenClientError):
    """Raised when the Qwen/DashScope response cannot be normalized."""


def call_qwen_chat(
    messages: list[Message],
    model: str | None = None,
    timeout_s: int = 60,
) -> ResponseObject:
    """Call Qwen chat completion and return a normalized response object."""
    _validate_messages(messages)
    _validate_timeout(timeout_s)
    selected_model = model or DEFAULT_QWEN_MODEL
    payload: dict[str, object] = {"model": selected_model, "messages": messages}
    raw_response = _call_with_retries(payload, timeout_s)
    return _normalize_chat_response(raw_response, selected_model)


def call_qwen_json(
    messages: list[Message],
    schema_name: str,
    timeout_s: int = 60,
) -> ResponseObject:
    """Call Qwen and parse the assistant response content as JSON."""
    if not schema_name:
        raise ValueError("schema_name must not be empty")
    response = call_qwen_chat(messages, timeout_s=timeout_s)
    content = str(response["content"])
    try:
        parsed_json = json.loads(content)
    except json.JSONDecodeError as error:
        raise QwenResponseError(f"Qwen response for {schema_name} was not valid JSON") from error
    response["schema_name"] = schema_name
    response["json"] = parsed_json
    return response


def generate_response(prompt: str, model: str | None = None) -> str:
    """Generate a plain-text response through Qwen chat completion."""
    response = call_qwen_chat([{"role": "user", "content": prompt}], model=model)
    return str(response["content"])


def _call_with_retries(payload: dict[str, object], timeout_s: int) -> dict[str, object]:
    api_key = _load_api_key()
    endpoint = os.environ.get(DASHSCOPE_ENDPOINT_ENV, DEFAULT_DASHSCOPE_ENDPOINT)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return _post_json(endpoint, headers, payload, timeout_s)
        except TimeoutError as error:
            last_error = error
        except QwenRequestError as error:
            last_error = error
        if attempt < MAX_ATTEMPTS:
            time.sleep(RETRY_BACKOFF_S * attempt)
    raise QwenRequestError(f"Qwen request failed after {MAX_ATTEMPTS} attempts") from last_error


def _post_json(
    endpoint: str,
    headers: dict[str, str],
    payload: dict[str, object],
    timeout_s: int,
) -> dict[str, object]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # nosec B310
            response_body = response.read().decode("utf-8")
    except TimeoutError:
        raise
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise QwenRequestError(f"Qwen HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        reason = str(error.reason)
        if "timed out" in reason.lower():
            raise TimeoutError(reason) from error
        raise QwenRequestError(f"Qwen request failed: {reason}") from error

    try:
        decoded = json.loads(response_body)
    except json.JSONDecodeError as error:
        raise QwenResponseError("Qwen response body was not valid JSON") from error
    if not isinstance(decoded, dict):
        raise QwenResponseError("Qwen response body must be a JSON object")
    return dict(decoded)


def _normalize_chat_response(raw_response: dict[str, object], model: str) -> ResponseObject:
    choice = _first_choice(raw_response)
    message = choice.get("message")
    if not isinstance(message, dict):
        raise QwenResponseError("Qwen response choice missing message object")
    content = message.get("content")
    if not isinstance(content, str):
        raise QwenResponseError("Qwen response message content must be a string")
    normalized_model = raw_response.get("model")
    return {
        "provider": "dashscope",
        "model": normalized_model if isinstance(normalized_model, str) else model,
        "content": content,
        "finish_reason": choice.get("finish_reason"),
        "usage": raw_response.get("usage", {}),
        "raw": raw_response,
    }


def _first_choice(raw_response: dict[str, object]) -> dict[str, Any]:
    choices = raw_response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise QwenResponseError("Qwen response missing choices")
    choice = choices[0]
    if not isinstance(choice, dict):
        raise QwenResponseError("Qwen response choice must be an object")
    return choice


def _load_api_key() -> str:
    api_key = os.environ.get(DASHSCOPE_API_KEY_ENV)
    if not api_key:
        raise QwenConfigurationError(
            f"Missing required environment variable: {DASHSCOPE_API_KEY_ENV}"
        )
    return api_key


def _validate_messages(messages: list[Message]) -> None:
    if not messages:
        raise ValueError("messages must not be empty")
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if not role or not content:
            raise ValueError("each message must include role and content")


def _validate_timeout(timeout_s: int) -> None:
    if timeout_s < 1:
        raise ValueError("timeout_s must be a positive integer")
