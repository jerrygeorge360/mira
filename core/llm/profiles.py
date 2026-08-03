"""Provider presets for OpenAI-compatible chat and embedding adapters."""

from __future__ import annotations

import os
from dataclasses import dataclass

from core.db.repositories import DATABASE_PATH_ENV, current_database_path, get_runtime_setting

LLM_PROFILE_ENV = "LLM_PROFILE"
LLM_PROFILE_SETTING = "llm_profile"
LLM_GATEWAY_SETTING = "llm_gateway"
PARITOK_ENABLED_ENV = "MIRA_PARITOK_ENABLED"


@dataclass(frozen=True)
class ProviderProfile:
    name: str
    api_key_env: str
    chat_endpoint: str
    chat_model: str
    response_format: str = "auto"
    embedding_api_key_env: str | None = None
    embedding_endpoint: str | None = None
    embedding_model: str | None = None
    embedding_dimensions: int | None = None


DASHSCOPE_PROFILE = ProviderProfile(
    name="dashscope",
    api_key_env="DASHSCOPE_API_KEY",
    chat_endpoint="https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions",
    chat_model="qwen-plus-2025-07-28",
    embedding_api_key_env="DASHSCOPE_API_KEY",
    embedding_endpoint="https://dashscope-intl.aliyuncs.com/compatible-mode/v1/embeddings",
    embedding_model="text-embedding-v4",
)

PROVIDER_PROFILES: dict[str, ProviderProfile] = {
    DASHSCOPE_PROFILE.name: DASHSCOPE_PROFILE,
    "siliconflow": ProviderProfile(
        name="siliconflow",
        api_key_env="SILICONFLOW_API_KEY",
        chat_endpoint="https://api.siliconflow.com/v1/chat/completions",
        chat_model="Qwen/Qwen3-32B",
        embedding_api_key_env="SILICONFLOW_API_KEY",
        embedding_endpoint="https://api.siliconflow.com/v1/embeddings",
        embedding_model="Qwen/Qwen3-Embedding-0.6B",
        embedding_dimensions=1024,
    ),
    "deepseek": ProviderProfile(
        name="deepseek",
        api_key_env="DEEPSEEK_API_KEY",
        chat_endpoint="https://api.deepseek.com/chat/completions",
        chat_model="deepseek-chat",
    ),
    "gemini": ProviderProfile(
        name="gemini",
        api_key_env="GEMINI_API_KEY",
        chat_endpoint="https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        chat_model="gemini-3.5-flash",
    ),
}


def active_profile(provider: str | None = None) -> ProviderProfile | None:
    """Return the configured provider preset, if one is known."""
    profile_name = (
        provider
        or _runtime_profile_name()
        or os.environ.get(LLM_PROFILE_ENV)
        or os.environ.get("LLM_PROVIDER")
    )
    if not profile_name:
        return None
    return PROVIDER_PROFILES.get(profile_name.casefold())


def active_profile_name() -> tuple[str | None, str]:
    """Return the selected provider profile name and where it came from."""
    configured = _runtime_profile_name()
    if configured:
        return configured.casefold(), "dashboard"
    env_profile = os.environ.get(LLM_PROFILE_ENV) or os.environ.get("LLM_PROVIDER")
    return (env_profile.casefold(), "env") if env_profile else (None, "default")


def active_gateway_name(explicit: str | None = None) -> tuple[str, str]:
    """Resolve direct or Paritok transport independently from the model provider."""
    if explicit:
        return _validated_gateway(explicit), "explicit"
    configured = _runtime_setting(LLM_GATEWAY_SETTING)
    if configured:
        return _validated_gateway(configured), "dashboard"
    enabled = os.environ.get(PARITOK_ENABLED_ENV, "").casefold().strip()
    return ("paritok", "env") if enabled in {"1", "true", "yes", "on"} else ("direct", "default")


def _runtime_profile_name() -> str | None:
    return _runtime_setting(LLM_PROFILE_SETTING)


def _runtime_setting(key: str) -> str | None:
    if current_database_path() is None and DATABASE_PATH_ENV not in os.environ:
        return None
    return get_runtime_setting(key)


def _validated_gateway(value: str) -> str:
    normalized = value.casefold().strip()
    if normalized not in {"direct", "paritok"}:
        raise ValueError("LLM gateway must be one of: direct, paritok")
    return normalized
