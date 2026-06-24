"""Verify the ISSUE-019 Qwen/DashScope adapter.

Ownership: MIRA contributors.
Related issue: ISSUE-019.
Architecture area: llm.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from core.llm import qwen


@pytest.fixture(autouse=True)
def dashscope_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep Qwen tests isolated from the real developer environment."""
    monkeypatch.delenv(qwen.DASHSCOPE_API_KEY_ENV, raising=False)
    monkeypatch.delenv(qwen.DASHSCOPE_ENDPOINT_ENV, raising=False)
    yield


def _chat_response(content: str, model: str = "qwen-plus") -> dict[str, object]:
    return {
        "model": model,
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"input_tokens": 4, "output_tokens": 2},
    }


def test_missing_api_key_raises_clear_error() -> None:
    """A missing DashScope key fails before any request is attempted."""
    with pytest.raises(qwen.QwenConfigurationError, match="DASHSCOPE_API_KEY"):
        qwen.call_qwen_chat([{"role": "user", "content": "hello"}])


def test_mocked_chat_call_returns_normalized_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """The chat adapter normalizes a mocked DashScope response."""
    captured_payload: dict[str, object] = {}

    def fake_post_json(
        endpoint: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_s: int,
    ) -> dict[str, object]:
        captured_payload.update(payload)
        assert endpoint == qwen.DEFAULT_DASHSCOPE_ENDPOINT
        assert headers["Authorization"] == "Bearer test-key"
        assert timeout_s == 12
        return _chat_response("hello from qwen", model="qwen-test")

    monkeypatch.setenv(qwen.DASHSCOPE_API_KEY_ENV, "test-key")
    monkeypatch.setattr(qwen, "_post_json", fake_post_json)

    response = qwen.call_qwen_chat(
        [{"role": "user", "content": "hello"}],
        model="qwen-test",
        timeout_s=12,
    )

    assert captured_payload["model"] == "qwen-test"
    assert response["provider"] == "dashscope"
    assert response["model"] == "qwen-test"
    assert response["content"] == "hello from qwen"
    assert response["finish_reason"] == "stop"
    assert response["usage"] == {"input_tokens": 4, "output_tokens": 2}


def test_json_call_parses_valid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """The JSON adapter parses assistant content into a structured object."""

    def fake_post_json(
        endpoint: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_s: int,
    ) -> dict[str, object]:
        return _chat_response('{"route": "quick", "sufficient": true}')

    monkeypatch.setenv(qwen.DASHSCOPE_API_KEY_ENV, "test-key")
    monkeypatch.setattr(qwen, "_post_json", fake_post_json)

    response = qwen.call_qwen_json(
        [{"role": "user", "content": "route this"}],
        schema_name="retrieval_route",
    )

    assert response["schema_name"] == "retrieval_route"
    assert response["json"] == {"route": "quick", "sufficient": True}


def test_timeout_retry_path_is_testable(monkeypatch: pytest.MonkeyPatch) -> None:
    """A transient timeout is retried before returning a normalized response."""
    attempts = 0

    def fake_post_json(
        endpoint: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_s: int,
    ) -> dict[str, object]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("timed out")
        return _chat_response("recovered")

    monkeypatch.setenv(qwen.DASHSCOPE_API_KEY_ENV, "test-key")
    monkeypatch.setattr(qwen, "_post_json", fake_post_json)
    monkeypatch.setattr(qwen.time, "sleep", lambda seconds: None)

    response = qwen.call_qwen_chat([{"role": "user", "content": "hello"}])

    assert attempts == 2
    assert response["content"] == "recovered"


def test_invalid_json_response_raises_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """The JSON adapter raises a schema-specific parse error."""

    def fake_post_json(
        endpoint: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_s: int,
    ) -> dict[str, object]:
        return _chat_response("not-json")

    monkeypatch.setenv(qwen.DASHSCOPE_API_KEY_ENV, "test-key")
    monkeypatch.setattr(qwen, "_post_json", fake_post_json)

    with pytest.raises(qwen.QwenResponseError, match="test_schema"):
        qwen.call_qwen_json([{"role": "user", "content": "json please"}], "test_schema")


def test_markdown_wrapped_json_is_accepted_for_prompt_schemas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Structured prompt outputs can be fenced in Markdown without breaking parsing."""

    def fake_post_json(
        endpoint: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_s: int,
    ) -> dict[str, object]:
        return _chat_response(
            """```json
            {"facts": []}
            ```"""
        )

    monkeypatch.setenv(qwen.DASHSCOPE_API_KEY_ENV, "test-key")
    monkeypatch.setattr(qwen, "_post_json", fake_post_json)

    response = qwen.call_qwen_json(
        [{"role": "user", "content": "extract facts"}],
        "atomic_fact_extraction",
    )

    assert response["json"] == {"facts": []}


def test_missing_required_keys_are_rejected_for_prompt_schemas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prompt-specific required keys are validated after parsing."""

    def fake_post_json(
        endpoint: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_s: int,
    ) -> dict[str, object]:
        return _chat_response('{"answer": "yes"}')

    monkeypatch.setenv(qwen.DASHSCOPE_API_KEY_ENV, "test-key")
    monkeypatch.setattr(qwen, "_post_json", fake_post_json)

    with pytest.raises(qwen.QwenResponseError, match="missing required keys"):
        qwen.call_qwen_json(
            [{"role": "user", "content": "extract facts"}],
            "atomic_fact_extraction",
        )
