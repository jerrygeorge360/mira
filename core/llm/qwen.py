"""OpenAI-compatible client boundary for model generation calls.

Ownership: Jerry.
Related issue: ISSUE-019.
Architecture area: llm.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.llm.json_helpers import (
    StructuredJsonError,
    coerce_or_reject_json,
    validate_required_keys,
)
from core.llm.profiles import LLM_PROFILE_ENV, active_profile
from core.llm.prompts import get_output_schema

LLM_API_KEY_ENV = "LLM_API_KEY"
LLM_CHAT_ENDPOINT_ENV = "LLM_CHAT_ENDPOINT"
LLM_PROVIDER_ENV = "LLM_PROVIDER"
LLM_MODEL_ENV = "LLM_MODEL"
LLM_RESPONSE_FORMAT_ENV = "LLM_RESPONSE_FORMAT"
DASHSCOPE_API_KEY_ENV = "DASHSCOPE_API_KEY"
DASHSCOPE_ENDPOINT_ENV = "DASHSCOPE_CHAT_ENDPOINT"
DEFAULT_QWEN_MODEL = "qwen-plus"
DEFAULT_DASHSCOPE_ENDPOINT = (
    "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions"
)
DEFAULT_LLM_PROVIDER = "dashscope"
DEFAULT_LLM_MODEL = DEFAULT_QWEN_MODEL
DEFAULT_LLM_CHAT_ENDPOINT = DEFAULT_DASHSCOPE_ENDPOINT
DEFAULT_LLM_RESPONSE_FORMAT = "auto"
MAX_ATTEMPTS = 3
MAX_JSON_VALIDATION_ATTEMPTS = 3
RETRY_BACKOFF_S = 0.25

Message = dict[str, str]
ResponseObject = dict[str, object]
Transport = Callable[[dict[str, object], int], dict[str, object]]


class LLMClientError(RuntimeError):
    """Base error for OpenAI-compatible adapter failures."""


class LLMConfigurationError(LLMClientError):
    """Raised when the OpenAI-compatible adapter is not configured."""


class LLMRequestError(LLMClientError):
    """Raised when an OpenAI-compatible request fails."""


class LLMResponseError(LLMClientError):
    """Raised when an OpenAI-compatible response cannot be normalized."""


QwenClientError = LLMClientError
QwenConfigurationError = LLMConfigurationError
QwenRequestError = LLMRequestError
QwenResponseError = LLMResponseError


def call_llm_chat(
    messages: list[Message],
    model: str | None = None,
    timeout_s: int = 60,
    provider: str | None = None,
    response_format: dict[str, object] | None = None,
) -> ResponseObject:
    """Call an OpenAI-compatible chat completion endpoint."""
    _validate_messages(messages)
    _validate_timeout(timeout_s)
    selected_model = model or _load_chat_model(provider)
    selected_provider = provider or _load_provider()
    payload: dict[str, object] = {"model": selected_model, "messages": messages}
    if response_format is not None:
        payload["response_format"] = response_format
    raw_response = _call_with_retries(payload, timeout_s)
    return _normalize_chat_response(raw_response, selected_model, selected_provider)


def call_llm_json(
    messages: list[Message],
    schema_name: str,
    model: str | None = None,
    timeout_s: int = 60,
    provider: str | None = None,
) -> ResponseObject:
    """Call an OpenAI-compatible model and parse assistant content as JSON."""
    if not schema_name:
        raise ValueError("schema_name must not be empty")
    validation_error: LLMResponseError | None = None
    active_messages = _schema_contract_messages(messages, schema_name)
    for attempt in range(1, MAX_JSON_VALIDATION_ATTEMPTS + 1):
        response = _call_llm_json_chat(
            active_messages,
            schema_name=schema_name,
            model=model,
            timeout_s=timeout_s,
            provider=provider,
        )
        try:
            return _attach_parsed_json(response, schema_name)
        except LLMResponseError as error:
            validation_error = error
            if attempt == MAX_JSON_VALIDATION_ATTEMPTS:
                break
            active_messages = _repair_messages(messages, schema_name, error)
    if validation_error is None:
        raise LLMResponseError(f"LLM response for {schema_name} failed validation")
    raise validation_error


def _call_llm_json_chat(
    messages: list[Message],
    schema_name: str,
    model: str | None,
    timeout_s: int,
    provider: str | None,
) -> ResponseObject:
    response_format = _response_format_for_schema(schema_name, provider)
    try:
        return call_llm_chat(
            messages,
            model=model,
            timeout_s=timeout_s,
            provider=provider,
            response_format=response_format,
        )
    except LLMRequestError as error:
        if not _should_fallback_to_json_object(response_format, error):
            raise
        return call_llm_chat(
            messages,
            model=model,
            timeout_s=timeout_s,
            provider=provider,
            response_format={"type": "json_object"},
        )


def _attach_parsed_json(response: ResponseObject, schema_name: str) -> ResponseObject:
    content = str(response["content"])
    try:
        parsed_json: object = coerce_or_reject_json(content)
    except StructuredJsonError as error:
        raise LLMResponseError(f"LLM response for {schema_name} was not valid JSON") from error
    parsed_json = _coerce_schema_root(parsed_json, schema_name)
    required_keys = _required_keys_for_schema(schema_name)
    expected_object = _schema_expects_object(schema_name)
    if required_keys:
        if not isinstance(parsed_json, dict):
            raise LLMResponseError(f"LLM response for {schema_name} must be a JSON object")
        if not validate_required_keys(parsed_json, required_keys):
            missing_keys = sorted(key for key in required_keys if key not in parsed_json)
            present_keys = sorted(str(key) for key in parsed_json)
            raise LLMResponseError(
                f"LLM response for {schema_name} was missing required keys "
                f"{missing_keys}; present keys: {present_keys}"
            )
    elif expected_object and not isinstance(parsed_json, dict):
        raise LLMResponseError(f"LLM response for {schema_name} must be a JSON object")
    response["schema_name"] = schema_name
    response["json"] = parsed_json
    return response


def call_qwen_chat(
    messages: list[Message],
    model: str | None = None,
    timeout_s: int = 60,
) -> ResponseObject:
    """Backward-compatible wrapper for the OpenAI-compatible chat adapter."""
    return call_llm_chat(messages, model=model, timeout_s=timeout_s)


LLM_CACHE_ENV = "MIRA_LLM_CACHE"


def _llm_cache_dir() -> Path | None:
    """Return the on-disk LLM cache directory if MIRA_LLM_CACHE is set, else None.

    Off by default. When set, identical (profile, model, schema, messages) calls reuse a
    prior response instead of hitting the provider -- a large speedup for the ablation,
    where the same slow-path ingestion prompts repeat across configs. Keyed on the exact
    prompt, so only truly-identical calls hit; it never returns a response for a different
    prompt.
    """
    raw = os.environ.get(LLM_CACHE_ENV)
    if not raw:
        return None
    path = Path(raw)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _llm_cache_key(messages: list[Message], schema_name: str) -> str:
    signature = json.dumps(
        {
            "profile": os.environ.get(LLM_PROFILE_ENV, ""),
            "model": os.environ.get(LLM_MODEL_ENV, ""),
            "schema": schema_name,
            "messages": messages,
        },
        sort_keys=True,
    )
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()


def call_qwen_json(
    messages: list[Message],
    schema_name: str,
    timeout_s: int = 60,
) -> ResponseObject:
    """Backward-compatible wrapper for the OpenAI-compatible JSON adapter.

    Transparently memoizes responses to disk when MIRA_LLM_CACHE is set (off by default).
    """
    cache_dir = _llm_cache_dir()
    if cache_dir is None:
        return call_llm_json(messages, schema_name=schema_name, timeout_s=timeout_s)
    cache_file = cache_dir / f"{_llm_cache_key(messages, schema_name)}.json"
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if isinstance(cached, dict):
                return cached
        except (json.JSONDecodeError, OSError):
            pass  # corrupt entry -> fall through to a fresh call
    response = call_llm_json(messages, schema_name=schema_name, timeout_s=timeout_s)
    with contextlib.suppress(OSError):  # a cache write failure must never break generation
        cache_file.write_text(json.dumps(response, sort_keys=True, default=str), encoding="utf-8")
    return response


def generate_response(prompt: str, model: str | None = None) -> str:
    """Generate a plain-text response through the configured chat completion."""
    response = call_llm_chat([{"role": "user", "content": prompt}], model=model)
    return str(response["content"])


def _call_with_retries(payload: dict[str, object], timeout_s: int) -> dict[str, object]:
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return _post_chat_completion(payload, timeout_s)
        except TimeoutError as error:
            last_error = error
        except LLMRequestError as error:
            if _is_response_format_unsupported(error):
                raise
            last_error = error
        if attempt < MAX_ATTEMPTS:
            time.sleep(RETRY_BACKOFF_S * attempt)
    detail = f": {last_error}" if last_error else ""
    raise LLMRequestError(
        f"LLM request failed after {MAX_ATTEMPTS} attempts{detail}"
    ) from last_error


def _post_chat_completion(
    payload: dict[str, object],
    timeout_s: int,
) -> dict[str, object]:
    try:
        client = _create_openai_client(timeout_s)
        completion = client.chat.completions.create(**payload)
    except ImportError as error:
        raise LLMConfigurationError(
            "Missing dependency: install the 'openai' package to use the LLM adapter"
        ) from error
    except LLMConfigurationError:
        raise
    except TimeoutError:
        raise
    except Exception as error:
        if error.__class__.__name__ == "APITimeoutError":
            raise TimeoutError(str(error)) from error
        raise LLMRequestError(f"LLM request failed: {error}") from error

    decoded = _openai_object_to_dict(completion)
    if not isinstance(decoded, dict):
        raise LLMResponseError("LLM response body must be a JSON object")
    return dict(decoded)


def _create_openai_client(timeout_s: int) -> Any:
    from openai import OpenAI

    return OpenAI(
        api_key=_load_api_key(),
        base_url=_load_base_url(),
        timeout=timeout_s,
    )


def _openai_object_to_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        if isinstance(dumped, dict):
            return dumped
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        dumped = to_dict()
        if isinstance(dumped, dict):
            return dumped
    raise LLMResponseError("LLM response body must be convertible to a JSON object")


def _normalize_chat_response(
    raw_response: dict[str, object],
    model: str,
    provider: str,
) -> ResponseObject:
    choice = _first_choice(raw_response)
    message = choice.get("message")
    if not isinstance(message, dict):
        raise LLMResponseError("LLM response choice missing message object")
    content = message.get("content")
    if not isinstance(content, str):
        raise LLMResponseError("LLM response message content must be a string")
    normalized_model = raw_response.get("model")
    return {
        "provider": provider,
        "model": normalized_model if isinstance(normalized_model, str) else model,
        "content": content,
        "finish_reason": choice.get("finish_reason"),
        "usage": raw_response.get("usage", {}),
        "raw": raw_response,
    }


def _first_choice(raw_response: dict[str, object]) -> dict[str, Any]:
    choices = raw_response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMResponseError("LLM response missing choices")
    choice = choices[0]
    if not isinstance(choice, dict):
        raise LLMResponseError("LLM response choice must be an object")
    return choice


def _load_api_key() -> str:
    profile = active_profile()
    profile_api_key = os.environ.get(profile.api_key_env) if profile else None
    api_key = (
        os.environ.get(LLM_API_KEY_ENV) or profile_api_key or os.environ.get(DASHSCOPE_API_KEY_ENV)
    )
    if not api_key:
        raise LLMConfigurationError(f"Missing required environment variable: {LLM_API_KEY_ENV}")
    return api_key


def _load_chat_endpoint() -> str:
    profile = active_profile()
    return (
        os.environ.get(LLM_CHAT_ENDPOINT_ENV)
        or (profile.chat_endpoint if profile else None)
        or os.environ.get(DASHSCOPE_ENDPOINT_ENV)
        or DEFAULT_LLM_CHAT_ENDPOINT
    )


def _load_chat_model(provider: str | None = None) -> str:
    profile = active_profile(provider)
    return os.environ.get(LLM_MODEL_ENV) or (profile.chat_model if profile else DEFAULT_LLM_MODEL)


def _load_provider() -> str:
    profile = active_profile()
    return (
        os.environ.get(LLM_PROVIDER_ENV)
        or os.environ.get(LLM_PROFILE_ENV)
        or (profile.name if profile else DEFAULT_LLM_PROVIDER)
    )


def _load_base_url() -> str:
    endpoint = _load_chat_endpoint().rstrip("/")
    suffix = "/chat/completions"
    if endpoint.endswith(suffix):
        return endpoint[: -len(suffix)]
    return endpoint


def _response_format_for_schema(
    schema_name: str,
    provider: str | None,
) -> dict[str, object]:
    profile = active_profile(provider)
    mode = os.environ.get(
        LLM_RESPONSE_FORMAT_ENV,
        profile.response_format if profile else DEFAULT_LLM_RESPONSE_FORMAT,
    ).casefold()
    if mode not in {"auto", "json_object", "json_schema"}:
        raise LLMConfigurationError(
            f"{LLM_RESPONSE_FORMAT_ENV} must be one of: auto, json_object, json_schema"
        )
    if mode == "json_object":
        return {"type": "json_object"}
    selected_provider = provider or _load_provider()
    if mode == "auto" and selected_provider.casefold() in {"deepseek"}:
        return {"type": "json_object"}
    schema = _schema_for_response_format(schema_name)
    if schema is None:
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {
            "name": _response_schema_name(schema_name),
            "strict": True,
            "schema": schema,
        },
    }


def _schema_for_response_format(schema_name: str) -> dict[str, object] | None:
    try:
        schema = get_output_schema(schema_name)
    except KeyError:
        return None
    return dict(schema) if isinstance(schema, dict) else None


def _response_schema_name(schema_name: str) -> str:
    normalized = "".join(
        char if char.isalnum() or char in ("_", "-") else "_" for char in schema_name
    )
    return normalized or "structured_response"


def _should_fallback_to_json_object(
    response_format: dict[str, object],
    error: LLMRequestError,
) -> bool:
    if response_format.get("type") != "json_schema":
        return False
    return _is_response_format_unsupported(error)


def _is_response_format_unsupported(error: LLMRequestError) -> bool:
    detail = str(error).casefold()
    return "response_format" in detail or "json_schema" in detail


def _repair_messages(
    messages: list[Message],
    schema_name: str,
    error: LLMResponseError,
) -> list[Message]:
    schema = _schema_for_response_format(schema_name)
    repair_instruction = (
        "Your previous response did not match the required JSON schema. "
        f"Return only a valid JSON object for schema {schema_name!r}, with all required keys. "
        f"Schema: {json.dumps(schema or {}, sort_keys=True)}. "
        f"Validation error: {error}"
    )
    return [
        *_schema_contract_messages(messages, schema_name),
        {"role": "user", "content": repair_instruction},
    ]


def _schema_contract_messages(messages: list[Message], schema_name: str) -> list[Message]:
    schema = _schema_for_response_format(schema_name)
    required_keys = sorted(_required_keys_for_schema(schema_name))
    contract = (
        "You are a strict JSON API. Return only one JSON object and no prose, "
        "markdown, code fences, or alternate top-level keys. "
        f"The top-level schema name is {schema_name!r}. "
        f"The required top-level keys are: {json.dumps(required_keys)}. "
        f"The exact JSON Schema is: {json.dumps(schema or {}, sort_keys=True)}."
    )
    if messages and messages[0].get("role") == "system":
        first = dict(messages[0])
        first["content"] = f"{contract}\n\n{first['content']}"
        return [first, *messages[1:]]
    return [{"role": "system", "content": contract}, *messages]


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


def _required_keys_for_schema(schema_name: str) -> set[str]:
    try:
        schema = get_output_schema(schema_name)
    except KeyError:
        return set()
    if not isinstance(schema, dict):
        return set()
    required = schema.get("required")
    if not isinstance(required, list):
        return set()
    return {str(key) for key in required if isinstance(key, str)}


def _schema_expects_object(schema_name: str) -> bool:
    try:
        schema = get_output_schema(schema_name)
    except KeyError:
        return False
    return isinstance(schema, dict) and schema.get("type") == "object"


def _coerce_schema_root(parsed_json: object, schema_name: str) -> object:
    if isinstance(parsed_json, dict):
        return parsed_json
    array_key = _single_required_array_key(schema_name)
    if array_key and isinstance(parsed_json, list):
        return {array_key: parsed_json}
    return parsed_json


def _single_required_array_key(schema_name: str) -> str | None:
    try:
        schema = get_output_schema(schema_name)
    except KeyError:
        return None
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return None
    required = schema.get("required")
    if not isinstance(required, list) or len(required) != 1:
        return None
    key = required[0]
    if not isinstance(key, str):
        return None
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return None
    property_schema = properties.get(key)
    if isinstance(property_schema, dict) and property_schema.get("type") == "array":
        return key
    return None
