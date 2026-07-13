"""Verify the ISSUE-019 Qwen/DashScope adapter.

Ownership: MIRA contributors.
Related issue: ISSUE-019.
Architecture area: llm.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from core.llm import qwen
from core.llm.profiles import LLM_PROFILE_ENV


@pytest.fixture(autouse=True)
def dashscope_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep Qwen tests isolated from the real developer environment."""
    monkeypatch.delenv(qwen.LLM_API_KEY_ENV, raising=False)
    monkeypatch.delenv(qwen.LLM_CHAT_ENDPOINT_ENV, raising=False)
    monkeypatch.delenv(qwen.LLM_PROVIDER_ENV, raising=False)
    monkeypatch.delenv(LLM_PROFILE_ENV, raising=False)
    monkeypatch.delenv(qwen.LLM_MODEL_ENV, raising=False)
    monkeypatch.delenv(qwen.LLM_RESPONSE_FORMAT_ENV, raising=False)
    monkeypatch.delenv(qwen.LLM_CACHE_ENV, raising=False)
    monkeypatch.delenv(qwen.DASHSCOPE_API_KEY_ENV, raising=False)
    monkeypatch.delenv(qwen.DASHSCOPE_ENDPOINT_ENV, raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
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
    """A missing LLM key fails before any request is attempted."""
    with pytest.raises(qwen.QwenConfigurationError, match="LLM_API_KEY"):
        qwen.call_qwen_chat([{"role": "user", "content": "hello"}])


def test_mocked_chat_call_returns_normalized_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """The chat adapter normalizes a mocked OpenAI-compatible response."""
    captured_payload: dict[str, object] = {}

    def fake_post_chat_completion(
        payload: dict[str, object],
        timeout_s: int,
    ) -> dict[str, object]:
        captured_payload.update(payload)
        assert timeout_s == 12
        return _chat_response("hello from deepseek", model="deepseek-chat")

    monkeypatch.setenv(qwen.LLM_API_KEY_ENV, "test-key")
    monkeypatch.setenv(qwen.LLM_CHAT_ENDPOINT_ENV, "https://api.deepseek.com/chat/completions")
    monkeypatch.setenv(qwen.LLM_PROVIDER_ENV, "deepseek")
    monkeypatch.setattr(qwen, "_post_chat_completion", fake_post_chat_completion)

    response = qwen.call_llm_chat(
        [{"role": "user", "content": "hello"}],
        model="deepseek-chat",
        timeout_s=12,
    )

    assert captured_payload["model"] == "deepseek-chat"
    assert response["provider"] == "deepseek"
    assert response["model"] == "deepseek-chat"
    assert response["content"] == "hello from deepseek"
    assert response["finish_reason"] == "stop"
    assert response["usage"] == {"input_tokens": 4, "output_tokens": 2}


def test_legacy_dashscope_environment_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    """The generic adapter preserves the existing DashScope configuration path."""

    def fake_post_chat_completion(
        payload: dict[str, object],
        timeout_s: int,
    ) -> dict[str, object]:
        assert payload["model"] == "qwen-test"
        return _chat_response("hello from qwen", model="qwen-test")

    monkeypatch.setenv(qwen.DASHSCOPE_API_KEY_ENV, "legacy-key")
    monkeypatch.setattr(qwen, "_post_chat_completion", fake_post_chat_completion)

    response = qwen.call_qwen_chat(
        [{"role": "user", "content": "hello"}],
        model="qwen-test",
    )

    assert response["provider"] == "dashscope"
    assert response["content"] == "hello from qwen"


def test_chat_endpoint_is_converted_to_openai_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OpenAI-compatible clients receive the base URL, not the full chat path."""
    monkeypatch.setenv(qwen.LLM_CHAT_ENDPOINT_ENV, "https://api.deepseek.com/chat/completions")

    assert qwen._load_base_url() == "https://api.deepseek.com"


def test_gemini_openai_endpoint_is_converted_to_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gemini's OpenAI-compatible endpoint works with OpenAI(base_url=...)."""
    monkeypatch.setenv(
        qwen.LLM_CHAT_ENDPOINT_ENV,
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    )

    assert qwen._load_base_url() == "https://generativelanguage.googleapis.com/v1beta/openai"


def test_profile_supplies_gemini_chat_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """A profile can select endpoint, model, provider, and provider-specific key."""
    monkeypatch.setenv(LLM_PROFILE_ENV, "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")

    assert qwen._load_api_key() == "gemini-key"
    assert qwen._load_chat_model() == "gemini-3.5-flash"
    assert qwen._load_provider() == "gemini"
    assert qwen._load_base_url() == "https://generativelanguage.googleapis.com/v1beta/openai"


def test_explicit_chat_env_overrides_profile_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Manual env values remain stronger than profile presets."""
    monkeypatch.setenv(LLM_PROFILE_ENV, "gemini")
    monkeypatch.setenv(qwen.LLM_API_KEY_ENV, "manual-key")
    monkeypatch.setenv(qwen.LLM_CHAT_ENDPOINT_ENV, "https://example.test/v1/chat/completions")
    monkeypatch.setenv(qwen.LLM_MODEL_ENV, "custom-model")
    monkeypatch.setenv(qwen.LLM_PROVIDER_ENV, "custom-provider")

    assert qwen._load_api_key() == "manual-key"
    assert qwen._load_chat_model() == "custom-model"
    assert qwen._load_provider() == "custom-provider"
    assert qwen._load_base_url() == "https://example.test/v1"


def test_legacy_dashscope_endpoint_is_converted_to_openai_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The DashScope chat endpoint remains compatible with OpenAI(base_url=...)."""
    monkeypatch.setenv(qwen.DASHSCOPE_ENDPOINT_ENV, qwen.DEFAULT_DASHSCOPE_ENDPOINT)

    assert qwen._load_base_url() == "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"


def test_json_call_parses_valid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """The JSON adapter parses assistant content into a structured object."""
    captured_payload: dict[str, object] = {}

    def fake_post_chat_completion(
        payload: dict[str, object],
        timeout_s: int,
    ) -> dict[str, object]:
        captured_payload.update(payload)
        return _chat_response('{"facts": []}')

    monkeypatch.setenv(qwen.DASHSCOPE_API_KEY_ENV, "test-key")
    monkeypatch.setattr(qwen, "_post_chat_completion", fake_post_chat_completion)

    response = qwen.call_qwen_json(
        [{"role": "user", "content": "extract facts"}],
        schema_name="atomic_fact_extraction",
    )

    assert response["schema_name"] == "atomic_fact_extraction"
    assert response["json"] == {"facts": []}
    response_format = captured_payload["response_format"]
    assert isinstance(response_format, dict)
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "atomic_fact_extraction"
    assert response_format["json_schema"]["strict"] is True


def test_deepseek_auto_mode_uses_json_object_response_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DeepSeek currently documents JSON object mode, not strict JSON schema mode."""
    captured_payload: dict[str, object] = {}

    def fake_post_chat_completion(
        payload: dict[str, object],
        timeout_s: int,
    ) -> dict[str, object]:
        captured_payload.update(payload)
        return _chat_response('{"facts": []}')

    monkeypatch.setenv(qwen.LLM_API_KEY_ENV, "test-key")
    monkeypatch.setenv(qwen.LLM_PROVIDER_ENV, "deepseek")
    monkeypatch.setattr(qwen, "_post_chat_completion", fake_post_chat_completion)

    response = qwen.call_qwen_json(
        [{"role": "user", "content": "extract facts"}],
        "atomic_fact_extraction",
    )

    assert response["json"] == {"facts": []}
    assert captured_payload["response_format"] == {"type": "json_object"}


def test_siliconflow_auto_mode_uses_json_schema_response_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SiliconFlow's Qwen models honor strict JSON schema, with json_object fallback."""
    captured_payload: dict[str, object] = {}

    def fake_post_chat_completion(
        payload: dict[str, object],
        timeout_s: int,
    ) -> dict[str, object]:
        captured_payload.update(payload)
        return _chat_response('{"facts": []}')

    monkeypatch.setenv(qwen.LLM_API_KEY_ENV, "test-key")
    monkeypatch.setenv(qwen.LLM_PROVIDER_ENV, "siliconflow")
    monkeypatch.setattr(qwen, "_post_chat_completion", fake_post_chat_completion)

    response = qwen.call_qwen_json(
        [{"role": "user", "content": "extract facts"}],
        "atomic_fact_extraction",
    )

    assert response["json"] == {"facts": []}
    response_format = captured_payload["response_format"]
    assert isinstance(response_format, dict)
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "atomic_fact_extraction"
    assert response_format["json_schema"]["strict"] is True


def test_gemini_auto_mode_uses_json_schema_response_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gemini OpenAI compatibility supports strict JSON schema requests."""
    captured_payload: dict[str, object] = {}

    def fake_post_chat_completion(
        payload: dict[str, object],
        timeout_s: int,
    ) -> dict[str, object]:
        captured_payload.update(payload)
        return _chat_response('{"facts": []}', model="gemini-3.5-flash")

    monkeypatch.setenv(qwen.LLM_API_KEY_ENV, "test-key")
    monkeypatch.setenv(qwen.LLM_PROVIDER_ENV, "gemini")
    monkeypatch.setattr(qwen, "_post_chat_completion", fake_post_chat_completion)

    response = qwen.call_qwen_json(
        [{"role": "user", "content": "extract facts"}],
        "atomic_fact_extraction",
    )

    assert response["json"] == {"facts": []}
    response_format = captured_payload["response_format"]
    assert isinstance(response_format, dict)
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "atomic_fact_extraction"
    assert response_format["json_schema"]["strict"] is True


def test_json_schema_request_falls_back_when_provider_rejects_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unsupported json_schema response_format falls back to json_object."""
    response_formats: list[object] = []

    def fake_post_chat_completion(
        payload: dict[str, object],
        timeout_s: int,
    ) -> dict[str, object]:
        response_formats.append(payload.get("response_format"))
        if len(response_formats) == 1:
            raise qwen.LLMRequestError("unsupported response_format: json_schema")
        return _chat_response('{"facts": []}')

    monkeypatch.setenv(qwen.LLM_API_KEY_ENV, "test-key")
    monkeypatch.setenv(qwen.LLM_RESPONSE_FORMAT_ENV, "json_schema")
    monkeypatch.setattr(qwen, "_post_chat_completion", fake_post_chat_completion)

    response = qwen.call_qwen_json(
        [{"role": "user", "content": "extract facts"}],
        "atomic_fact_extraction",
    )

    assert response["json"] == {"facts": []}
    assert response_formats[0]["type"] == "json_schema"
    assert response_formats[1] == {"type": "json_object"}


def test_json_validation_retries_with_schema_repair_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed JSON objects get one schema-repair retry before failing."""
    prompts: list[list[dict[str, str]]] = []

    def fake_post_chat_completion(
        payload: dict[str, object],
        timeout_s: int,
    ) -> dict[str, object]:
        messages = payload["messages"]
        assert isinstance(messages, list)
        prompts.append(messages)
        if len(prompts) == 1:
            return _chat_response('{"answer": "wrong key"}')
        return _chat_response('{"facts": []}')

    monkeypatch.setenv(qwen.DASHSCOPE_API_KEY_ENV, "test-key")
    monkeypatch.setattr(qwen, "_post_chat_completion", fake_post_chat_completion)

    response = qwen.call_qwen_json(
        [{"role": "user", "content": "extract facts"}],
        "atomic_fact_extraction",
    )

    assert response["json"] == {"facts": []}
    assert len(prompts) == 2
    assert "previous response did not match" in prompts[1][-1]["content"]


def test_single_array_schema_accepts_bare_array_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Some providers return [] for empty single-array schemas; normalize that."""

    def fake_post_chat_completion(
        payload: dict[str, object],
        timeout_s: int,
    ) -> dict[str, object]:
        return _chat_response("[]")

    monkeypatch.setenv(qwen.DASHSCOPE_API_KEY_ENV, "test-key")
    monkeypatch.setattr(qwen, "_post_chat_completion", fake_post_chat_completion)

    response = qwen.call_qwen_json(
        [{"role": "user", "content": "extract facts"}],
        "atomic_fact_extraction",
    )

    assert response["json"] == {"facts": []}


def test_timeout_retry_path_is_testable(monkeypatch: pytest.MonkeyPatch) -> None:
    """A transient timeout is retried before returning a normalized response."""
    attempts = 0

    def fake_post_chat_completion(
        payload: dict[str, object],
        timeout_s: int,
    ) -> dict[str, object]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("timed out")
        return _chat_response("recovered")

    monkeypatch.setenv(qwen.DASHSCOPE_API_KEY_ENV, "test-key")
    monkeypatch.setattr(qwen, "_post_chat_completion", fake_post_chat_completion)
    monkeypatch.setattr(qwen.time, "sleep", lambda seconds: None)

    response = qwen.call_qwen_chat([{"role": "user", "content": "hello"}])

    assert attempts == 2
    assert response["content"] == "recovered"


def test_invalid_json_response_raises_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """The JSON adapter raises a schema-specific parse error."""

    def fake_post_chat_completion(
        payload: dict[str, object],
        timeout_s: int,
    ) -> dict[str, object]:
        return _chat_response("not-json")

    monkeypatch.setenv(qwen.DASHSCOPE_API_KEY_ENV, "test-key")
    monkeypatch.setattr(qwen, "_post_chat_completion", fake_post_chat_completion)

    with pytest.raises(qwen.QwenResponseError, match="test_schema"):
        qwen.call_qwen_json([{"role": "user", "content": "json please"}], "test_schema")


def test_markdown_wrapped_json_is_accepted_for_prompt_schemas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Structured prompt outputs can be fenced in Markdown without breaking parsing."""

    def fake_post_chat_completion(
        payload: dict[str, object],
        timeout_s: int,
    ) -> dict[str, object]:
        return _chat_response(
            """```json
            {"facts": []}
            ```"""
        )

    monkeypatch.setenv(qwen.DASHSCOPE_API_KEY_ENV, "test-key")
    monkeypatch.setattr(qwen, "_post_chat_completion", fake_post_chat_completion)

    response = qwen.call_qwen_json(
        [{"role": "user", "content": "extract facts"}],
        "atomic_fact_extraction",
    )

    assert response["json"] == {"facts": []}


def test_missing_required_keys_are_rejected_for_prompt_schemas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prompt-specific required keys are validated after parsing."""

    def fake_post_chat_completion(
        payload: dict[str, object],
        timeout_s: int,
    ) -> dict[str, object]:
        return _chat_response('{"answer": "yes"}')

    monkeypatch.setenv(qwen.DASHSCOPE_API_KEY_ENV, "test-key")
    monkeypatch.setattr(qwen, "_post_chat_completion", fake_post_chat_completion)

    with pytest.raises(qwen.QwenResponseError, match="missing required keys"):
        qwen.call_qwen_json(
            [{"role": "user", "content": "extract facts"}],
            "atomic_fact_extraction",
        )
