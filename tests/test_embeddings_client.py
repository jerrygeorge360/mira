"""Verify the OpenAI-compatible embeddings adapter."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from core.llm import embeddings


@pytest.fixture(autouse=True)
def embedding_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep embedding tests isolated from the real developer environment."""
    monkeypatch.delenv(embeddings.EMBEDDING_API_KEY_ENV, raising=False)
    monkeypatch.delenv(embeddings.EMBEDDING_ENDPOINT_ENV, raising=False)
    monkeypatch.delenv(embeddings.EMBEDDING_MODEL_ENV, raising=False)
    monkeypatch.delenv(embeddings.EMBEDDING_DIMENSIONS_ENV, raising=False)
    monkeypatch.delenv(embeddings.EMBEDDING_MODE_ENV, raising=False)
    monkeypatch.delenv(embeddings.EMBEDDING_FALLBACK_ENV, raising=False)
    monkeypatch.delenv(embeddings.LOCAL_EMBEDDING_PROVIDER_ENV, raising=False)
    monkeypatch.delenv(embeddings.LOCAL_EMBEDDING_MODEL_ENV, raising=False)
    monkeypatch.delenv(embeddings.LLM_API_KEY_ENV, raising=False)
    embeddings._LOCAL_EMBEDDING_MODEL = None
    embeddings._LOCAL_EMBEDDING_MODEL_NAME = None
    yield
    embeddings._LOCAL_EMBEDDING_MODEL = None
    embeddings._LOCAL_EMBEDDING_MODEL_NAME = None


def test_embedding_dimensions_are_passed_to_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_post_embedding(text: str, model: str, timeout_s: int) -> list[float]:
        captured["text"] = text
        captured["model"] = model
        captured["timeout_s"] = timeout_s
        captured["dimensions"] = embeddings._embedding_dimensions()
        return [0.1, 0.2, 0.3]

    monkeypatch.setenv(embeddings.EMBEDDING_API_KEY_ENV, "test-key")
    monkeypatch.setenv(embeddings.EMBEDDING_MODEL_ENV, "Qwen/Qwen3-Embedding-0.6B")
    monkeypatch.setenv(embeddings.EMBEDDING_DIMENSIONS_ENV, "1024")
    monkeypatch.setattr(embeddings, "_post_embedding", fake_post_embedding)

    result = embeddings.embed_text("semantic memory", timeout_s=7)

    assert result == [0.1, 0.2, 0.3]
    assert captured == {
        "text": "semantic memory",
        "model": "Qwen/Qwen3-Embedding-0.6B",
        "timeout_s": 7,
        "dimensions": 1024,
    }


def test_deterministic_mode_never_requires_provider_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(embeddings.EMBEDDING_MODE_ENV, "deterministic")

    result = embeddings.embed_text("offline memory")

    assert len(result) == embeddings.DETERMINISTIC_DIMENSIONS


def test_local_mode_uses_fastembed_model(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeFastEmbedModel:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def embed(self, texts: list[str]) -> list[list[float]]:
            self.calls.append(texts)
            return [[0.4, 0.5, 0.6]]

    fake_model = FakeFastEmbedModel()
    loaded_models: list[str] = []

    def fake_loader(model_name: str) -> FakeFastEmbedModel:
        loaded_models.append(model_name)
        return fake_model

    monkeypatch.setenv(embeddings.EMBEDDING_MODE_ENV, "local")
    monkeypatch.setenv(embeddings.LOCAL_EMBEDDING_MODEL_ENV, "BAAI/bge-small-en-v1.5")
    monkeypatch.setattr(embeddings, "_load_fastembed_model", fake_loader)

    result = embeddings.embed_text("local memory")

    assert result == [0.4, 0.5, 0.6]
    assert loaded_models == ["BAAI/bge-small-en-v1.5"]
    assert fake_model.calls == [["local memory"]]


def test_local_mode_rejects_unknown_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(embeddings.EMBEDDING_MODE_ENV, "local")
    monkeypatch.setenv(embeddings.LOCAL_EMBEDDING_PROVIDER_ENV, "other")

    with pytest.raises(embeddings.LLMConfigurationError, match="LOCAL_EMBEDDING_PROVIDER"):
        embeddings.embed_text("local memory")
