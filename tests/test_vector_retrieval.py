"""Tests for the vector retrieval boundary."""

from __future__ import annotations

from core.retrieval import vector


def test_vector_search_logs_and_skips_chroma_runtime_failures(monkeypatch) -> None:
    """A corrupt Chroma collection must not crash chat retrieval."""
    logged: list[dict[str, object]] = []

    monkeypatch.setattr(vector, "embed_text", lambda query: [0.1, 0.2])

    def _raise_chroma_error(*args: object, **kwargs: object) -> list[dict[str, object]]:
        raise RuntimeError("Error executing plan: Internal error: Error finding id")

    monkeypatch.setattr(vector.chroma, "query_embeddings", _raise_chroma_error)
    monkeypatch.setattr(
        vector,
        "log_event",
        lambda event, message, **fields: logged.append(
            {"event": event, "message": message, **fields}
        ),
    )

    results = vector.vector_search(
        "What do I prefer?",
        collections=("observations",),
        workspace_id="workspace_1",
    )

    assert results == []
    assert logged
    assert logged[0]["event"] == "vector_search_failed"
    assert logged[0]["collection"] == "observations"
    assert logged[0]["error_type"] == "RuntimeError"
    assert "Error finding id" in str(logged[0]["error_message"])
