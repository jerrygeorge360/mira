"""OpenAI-compatible embedding provider for vector indexing and retrieval."""

from __future__ import annotations

import hashlib
import math
import os
import re
import time

from core.llm.profiles import active_profile
from core.llm.qwen import (
    DASHSCOPE_API_KEY_ENV,
    DASHSCOPE_ENDPOINT_ENV,
    DEFAULT_DASHSCOPE_ENDPOINT,
    LLM_API_KEY_ENV,
    LLM_CHAT_ENDPOINT_ENV,
    LLMConfigurationError,
    LLMRequestError,
)

EMBEDDING_API_KEY_ENV = "EMBEDDING_API_KEY"
EMBEDDING_ENDPOINT_ENV = "EMBEDDING_ENDPOINT"
EMBEDDING_MODEL_ENV = "EMBEDDING_MODEL"
EMBEDDING_DIMENSIONS_ENV = "EMBEDDING_DIMENSIONS"
EMBEDDING_MODE_ENV = "EMBEDDING_MODE"
EMBEDDING_FALLBACK_ENV = "EMBEDDING_FALLBACK"
LOCAL_EMBEDDING_PROVIDER_ENV = "LOCAL_EMBEDDING_PROVIDER"
LOCAL_EMBEDDING_MODEL_ENV = "LOCAL_EMBEDDING_MODEL"
DEFAULT_EMBEDDING_MODEL = "text-embedding-v4"
DEFAULT_EMBEDDING_MODE = "auto"
DEFAULT_EMBEDDING_FALLBACK = "deterministic"
DEFAULT_LOCAL_EMBEDDING_PROVIDER = "fastembed"
DEFAULT_LOCAL_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
MAX_ATTEMPTS = 3
RETRY_BACKOFF_S = 0.25
DETERMINISTIC_DIMENSIONS = 8

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_'-]+")
STOPWORDS = frozenset({"a", "an", "the", "is", "are", "of", "to", "and", "for", "in", "on"})

_LOCAL_EMBEDDING_MODEL: object | None = None
_LOCAL_EMBEDDING_MODEL_NAME: str | None = None


def embed_text(text: str, *, model: str | None = None, timeout_s: int = 30) -> list[float]:
    """Embed text using an OpenAI-compatible embeddings endpoint.

    If no embedding API key is configured, the function falls back to the old
    deterministic hash embedding. That keeps unit tests and offline development
    usable while production can opt into real embeddings through environment
    variables.
    """
    if not text.strip():
        raise ValueError("text must not be empty")
    mode = _embedding_mode()
    if mode == "deterministic":
        return deterministic_embedding(text)
    if mode == "local":
        return _embed_local_text(text)
    if mode != "auto":
        raise LLMConfigurationError(
            f"{EMBEDDING_MODE_ENV} must be one of: auto, local, deterministic"
        )
    if not _has_embedding_credentials():
        if _fallback_mode() == "error":
            raise LLMConfigurationError(
                f"Missing {EMBEDDING_API_KEY_ENV} or {LLM_API_KEY_ENV} for embeddings"
            )
        return deterministic_embedding(text)
    return _embed_with_retries(text, model or _embedding_model(), timeout_s)


def deterministic_embedding(text: str, dimensions: int = DETERMINISTIC_DIMENSIONS) -> list[float]:
    """Return a deterministic local embedding for tests and offline development."""
    if dimensions < 1:
        raise ValueError("dimensions must be positive")
    vector = [0.0] * dimensions
    for token in _tokens(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        vector[digest[0] % dimensions] += 1.0
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return [1.0, *([0.0] * (dimensions - 1))]
    return [value / norm for value in vector]


def _embed_local_text(text: str) -> list[float]:
    provider = os.environ.get(
        LOCAL_EMBEDDING_PROVIDER_ENV,
        DEFAULT_LOCAL_EMBEDDING_PROVIDER,
    ).casefold()
    if provider != "fastembed":
        raise LLMConfigurationError(f"{LOCAL_EMBEDDING_PROVIDER_ENV} must be: fastembed")

    model = _load_fastembed_model(_local_embedding_model())
    try:
        vector = next(iter(model.embed([text])))  # type: ignore[attr-defined]
    except Exception as error:
        raise LLMRequestError(f"Local embedding failed: {error}") from error
    return [float(value) for value in vector]


def _load_fastembed_model(model_name: str) -> object:
    global _LOCAL_EMBEDDING_MODEL, _LOCAL_EMBEDDING_MODEL_NAME
    if _LOCAL_EMBEDDING_MODEL is not None and model_name == _LOCAL_EMBEDDING_MODEL_NAME:
        return _LOCAL_EMBEDDING_MODEL
    try:
        from fastembed import TextEmbedding
    except ImportError as error:
        raise LLMConfigurationError(
            "Missing dependency: install 'fastembed' to use EMBEDDING_MODE=local"
        ) from error
    _LOCAL_EMBEDDING_MODEL = TextEmbedding(model_name=model_name)
    _LOCAL_EMBEDDING_MODEL_NAME = model_name
    return _LOCAL_EMBEDDING_MODEL


def _embed_with_retries(text: str, model: str, timeout_s: int) -> list[float]:
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return _post_embedding(text, model, timeout_s)
        except TimeoutError as error:
            last_error = error
        except LLMRequestError as error:
            last_error = error
        if attempt < MAX_ATTEMPTS:
            time.sleep(RETRY_BACKOFF_S * attempt)
    detail = f": {last_error}" if last_error else ""
    raise LLMRequestError(
        f"Embedding request failed after {MAX_ATTEMPTS} attempts{detail}"
    ) from last_error


def _post_embedding(text: str, model: str, timeout_s: int) -> list[float]:
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=_embedding_api_key(),
            base_url=_embedding_base_url(),
            timeout=timeout_s,
        )
        dimensions = _embedding_dimensions()
        if dimensions is not None:
            response = client.embeddings.create(model=model, input=text, dimensions=dimensions)
        else:
            response = client.embeddings.create(model=model, input=text)
    except ImportError as error:
        raise LLMConfigurationError(
            "Missing dependency: install the 'openai' package to use embeddings"
        ) from error
    except LLMConfigurationError:
        raise
    except TimeoutError:
        raise
    except Exception as error:
        if error.__class__.__name__ == "APITimeoutError":
            raise TimeoutError(str(error)) from error
        raise LLMRequestError(f"Embedding request failed: {error}") from error

    decoded = _openai_object_to_dict(response)
    data = decoded.get("data")
    if not isinstance(data, list) or not data:
        raise LLMRequestError("Embedding response missing data")
    first = data[0]
    if not isinstance(first, dict):
        raise LLMRequestError("Embedding response item must be an object")
    embedding = first.get("embedding")
    if not isinstance(embedding, list) or not embedding:
        raise LLMRequestError("Embedding response missing embedding vector")
    return [float(value) for value in embedding]


def _embedding_api_key() -> str:
    profile = active_profile()
    profile_api_key_env = profile.embedding_api_key_env or profile.api_key_env if profile else None
    profile_api_key = os.environ.get(profile_api_key_env) if profile_api_key_env else None
    api_key = (
        os.environ.get(EMBEDDING_API_KEY_ENV)
        or os.environ.get(LLM_API_KEY_ENV)
        or profile_api_key
        or os.environ.get(DASHSCOPE_API_KEY_ENV)
    )
    if not api_key:
        raise LLMConfigurationError(
            f"Missing required environment variable: {EMBEDDING_API_KEY_ENV}"
        )
    return api_key


def _embedding_base_url() -> str:
    profile = active_profile()
    endpoint = (
        os.environ.get(EMBEDDING_ENDPOINT_ENV)
        or (profile.embedding_endpoint if profile else None)
        or _derived_embedding_endpoint()
    ).rstrip("/")
    suffix = "/embeddings"
    if endpoint.endswith(suffix):
        return endpoint[: -len(suffix)]
    return endpoint


def _derived_embedding_endpoint() -> str:
    profile = active_profile()
    chat_endpoint = (
        os.environ.get(LLM_CHAT_ENDPOINT_ENV)
        or (profile.chat_endpoint if profile else None)
        or os.environ.get(DASHSCOPE_ENDPOINT_ENV)
        or DEFAULT_DASHSCOPE_ENDPOINT
    ).rstrip("/")
    suffix = "/chat/completions"
    if chat_endpoint.endswith(suffix):
        return f"{chat_endpoint[: -len(suffix)]}/embeddings"
    return f"{chat_endpoint}/embeddings"


def _embedding_model() -> str:
    profile = active_profile()
    return os.environ.get(EMBEDDING_MODEL_ENV) or (
        profile.embedding_model if profile and profile.embedding_model else DEFAULT_EMBEDDING_MODEL
    )


def _local_embedding_model() -> str:
    return os.environ.get(LOCAL_EMBEDDING_MODEL_ENV, DEFAULT_LOCAL_EMBEDDING_MODEL)


def _embedding_dimensions() -> int | None:
    raw_value = os.environ.get(EMBEDDING_DIMENSIONS_ENV)
    profile = active_profile()
    if raw_value is None or not raw_value.strip():
        return profile.embedding_dimensions if profile else None
    try:
        dimensions = int(raw_value)
    except ValueError as error:
        raise LLMConfigurationError(f"{EMBEDDING_DIMENSIONS_ENV} must be an integer") from error
    if dimensions < 1:
        raise LLMConfigurationError(f"{EMBEDDING_DIMENSIONS_ENV} must be positive")
    return dimensions


def _embedding_mode() -> str:
    return os.environ.get(EMBEDDING_MODE_ENV, DEFAULT_EMBEDDING_MODE).casefold()


def _fallback_mode() -> str:
    return os.environ.get(EMBEDDING_FALLBACK_ENV, DEFAULT_EMBEDDING_FALLBACK).casefold()


def _has_embedding_credentials() -> bool:
    profile = active_profile()
    profile_api_key_env = profile.embedding_api_key_env or profile.api_key_env if profile else None
    return bool(
        os.environ.get(EMBEDDING_API_KEY_ENV)
        or os.environ.get(LLM_API_KEY_ENV)
        or (os.environ.get(profile_api_key_env) if profile_api_key_env else None)
        or os.environ.get(DASHSCOPE_API_KEY_ENV)
    )


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in TOKEN_PATTERN.findall(value.casefold())
        if len(token) > 1 and token not in STOPWORDS
    }


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
    raise LLMRequestError("Embedding response body must be convertible to a JSON object")
