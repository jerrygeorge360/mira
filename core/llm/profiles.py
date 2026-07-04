"""Provider presets for OpenAI-compatible chat and embedding adapters."""

from __future__ import annotations

import os
from dataclasses import dataclass

LLM_PROFILE_ENV = "LLM_PROFILE"


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
    chat_model="qwen-plus",
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
    profile_name = provider or os.environ.get(LLM_PROFILE_ENV) or os.environ.get("LLM_PROVIDER")
    if not profile_name:
        return None
    return PROVIDER_PROFILES.get(profile_name.casefold())
