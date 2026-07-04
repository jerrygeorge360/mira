"""Verify the provider smoke-check script."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from core.llm import embeddings, qwen
from core.llm.profiles import LLM_PROFILE_ENV
from scripts import check_provider


@pytest.fixture(autouse=True)
def provider_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv(qwen.LLM_API_KEY_ENV, raising=False)
    monkeypatch.delenv(qwen.LLM_PROVIDER_ENV, raising=False)
    monkeypatch.delenv(LLM_PROFILE_ENV, raising=False)
    monkeypatch.delenv(embeddings.EMBEDDING_API_KEY_ENV, raising=False)
    monkeypatch.delenv(embeddings.EMBEDDING_MODE_ENV, raising=False)
    monkeypatch.delenv(embeddings.EMBEDDING_MODEL_ENV, raising=False)
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    yield


def test_provider_check_reports_chat_and_embeddings(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_chat(
        messages: list[dict[str, str]],
        schema_name: str,
        timeout_s: int = 60,
    ) -> dict[str, object]:
        return {
            "provider": "siliconflow",
            "model": "Qwen/Qwen3-32B",
            "schema_name": schema_name,
            "json": {"facts": []},
        }

    monkeypatch.setattr(check_provider, "call_llm_json", fake_chat)
    monkeypatch.setenv(embeddings.EMBEDDING_MODE_ENV, "deterministic")

    exit_code = check_provider.main([])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "chat ok provider=siliconflow model=Qwen/Qwen3-32B" in output
    assert "embeddings ok source=deterministic" in output


def test_provider_check_can_require_live_embeddings(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        check_provider,
        "call_llm_json",
        lambda messages, schema_name, timeout_s=60: {
            "provider": "test",
            "model": "test",
            "schema_name": schema_name,
            "json": {"facts": []},
        },
    )
    monkeypatch.setenv(embeddings.EMBEDDING_MODE_ENV, "deterministic")

    exit_code = check_provider.main(["--require-live-embeddings"])

    error_output = capsys.readouterr().err
    assert exit_code == 2
    assert "deterministic fallback" in error_output


def test_provider_check_counts_profile_embedding_key(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        check_provider,
        "call_llm_json",
        lambda messages, schema_name, timeout_s=60: {
            "provider": "siliconflow",
            "model": "Qwen/Qwen3-32B",
            "schema_name": schema_name,
            "json": {"facts": []},
        },
    )
    monkeypatch.setattr(embeddings, "embed_text", lambda text, timeout_s=30: [0.1, 0.2])
    monkeypatch.setenv(LLM_PROFILE_ENV, "siliconflow")
    monkeypatch.setenv("SILICONFLOW_API_KEY", "test-key")
    monkeypatch.setenv(embeddings.EMBEDDING_MODE_ENV, "auto")

    exit_code = check_provider.main(["--require-live-embeddings"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "embeddings ok source=provider model=Qwen/Qwen3-Embedding-0.6B" in output
