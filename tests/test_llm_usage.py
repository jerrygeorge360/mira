"""Verify provider-agnostic LLM usage accounting."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from core.db.repositories import (
    configure_database,
    list_llm_usage_events,
    summarize_llm_usage_run,
)
from core.db.schema import LEGACY_WORKSPACE_ID
from core.llm import qwen
from core.llm.usage import llm_usage_context, prompt_fingerprint


@pytest.fixture
def usage_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "usage.sqlite3"
    configure_database(path)
    monkeypatch.setenv(qwen.LLM_API_KEY_ENV, "test-key")
    monkeypatch.setenv(qwen.LLM_PROVIDER_ENV, "test-provider")
    monkeypatch.delenv(qwen.PARITOK_ENABLED_ENV, raising=False)
    monkeypatch.delenv(qwen.PARITOK_BASE_URL_ENV, raising=False)
    monkeypatch.delenv(qwen.PARITOK_UPSTREAM_PROFILE_ENV, raising=False)
    return path


def test_provider_reported_usage_is_persisted_per_call(
    usage_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del usage_database
    messages = [{"role": "user", "content": "private prompt content"}]

    def fake_post(payload: dict[str, object], timeout_s: int) -> dict[str, object]:
        del payload, timeout_s
        return {
            "id": "provider-request-1",
            "model": "test-model",
            "choices": [
                {"message": {"content": "response"}, "finish_reason": "stop"},
            ],
            "usage": {
                "prompt_tokens": 41,
                "completion_tokens": 9,
                "total_tokens": 50,
                "prompt_tokens_details": {"cached_tokens": 7},
            },
        }

    monkeypatch.setattr(qwen, "_post_chat_completion", fake_post)
    with llm_usage_context(
        run_id="run-provider",
        workspace_id=LEGACY_WORKSPACE_ID,
        component="test",
    ):
        response = qwen.call_llm_chat(messages, model="test-model", operation="answer_generation")

    records = list_llm_usage_events(run_id="run-provider")
    assert len(records) == 1
    record = records[0]
    assert response["usage_event_id"] == record["id"]
    assert record["usage_source"] == "provider"
    assert record["gateway"] == "direct"
    assert record["input_tokens"] == 41
    assert record["output_tokens"] == 9
    assert record["cached_input_tokens"] == 7
    assert record["prompt_fingerprint"] == prompt_fingerprint(messages)
    assert "private prompt content" not in repr(record)


def test_missing_provider_usage_is_explicitly_marked_as_estimated(
    usage_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del usage_database

    def fake_post(payload: dict[str, object], timeout_s: int) -> dict[str, object]:
        del payload, timeout_s
        return {
            "model": "test-model",
            "choices": [{"message": {"content": "answer"}, "finish_reason": "stop"}],
        }

    monkeypatch.setattr(qwen, "_post_chat_completion", fake_post)
    with llm_usage_context(
        run_id="run-estimated",
        workspace_id=LEGACY_WORKSPACE_ID,
        component="test",
    ):
        qwen.call_llm_chat([{"role": "user", "content": "hello"}], model="test-model")

    record = list_llm_usage_events(run_id="run-estimated")[0]
    assert record["usage_source"] == "estimated"
    assert record["input_tokens"] is None
    assert int(record["estimated_input_tokens"]) > 0
    summary = summarize_llm_usage_run("run-estimated")
    assert summary["fully_measured"] is False
    assert summary["provider_measured_calls"] == 0


def test_gateway_override_is_recorded_without_changing_the_provider(
    usage_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del usage_database
    captured_base_urls: list[str] = []

    def fake_post(payload: dict[str, object], timeout_s: int) -> dict[str, object]:
        del payload, timeout_s
        captured_base_urls.append(qwen._load_base_url())
        return {
            "model": "test-model",
            "choices": [{"message": {"content": "answer"}, "finish_reason": "stop"}],
            "usage": {"input_tokens": 5, "output_tokens": 2},
        }

    monkeypatch.setenv(qwen.LLM_CHAT_ENDPOINT_ENV, "https://provider.test/v1/chat/completions")
    monkeypatch.setenv(qwen.PARITOK_BASE_URL_ENV, "http://paritok.test:8080/v1")
    monkeypatch.setattr(qwen, "_post_chat_completion", fake_post)
    with llm_usage_context(
        run_id="run-gateways",
        workspace_id=LEGACY_WORKSPACE_ID,
        component="comparison",
    ):
        qwen.call_llm_chat(
            [{"role": "user", "content": "same prompt"}],
            model="test-model",
            gateway="direct",
        )
        qwen.call_llm_chat(
            [{"role": "user", "content": "same prompt"}],
            model="test-model",
            gateway="paritok",
        )

    assert captured_base_urls == ["https://provider.test/v1", "http://paritok.test:8080/v1"]
    records = list_llm_usage_events(run_id="run-gateways")
    assert {record["gateway"] for record in records} == {"direct", "paritok"}
    assert {record["provider"] for record in records} == {"test-provider"}


def test_paritok_request_savings_are_persisted_and_summarized(
    usage_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del usage_database

    def fake_post(payload: dict[str, object], timeout_s: int) -> dict[str, object]:
        del payload, timeout_s
        return {
            "model": "test-model",
            "choices": [{"message": {"content": "answer"}, "finish_reason": "stop"}],
            "usage": {"input_tokens": 70, "output_tokens": 5},
            "_mira_gateway_usage": {
                "input_tokens_original": 100,
                "input_tokens_compressed": 60,
                "tokens_saved": 40,
            },
        }

    monkeypatch.setattr(qwen, "_post_chat_completion", fake_post)
    with llm_usage_context(
        run_id="run-paritok-savings",
        workspace_id=LEGACY_WORKSPACE_ID,
        component="agent",
    ):
        qwen.call_llm_chat(
            [{"role": "user", "content": "same prompt"}],
            model="test-model",
            gateway="paritok",
        )

    record = list_llm_usage_events(run_id="run-paritok-savings")[0]
    assert record["gateway_input_tokens_original"] == 100
    assert record["gateway_input_tokens_compressed"] == 60
    assert record["gateway_tokens_saved"] == 40
    summary = summarize_llm_usage_run("run-paritok-savings")
    assert summary["gateway_tokens_saved"] == 40
    assert summary["paritok_calls"] == 1
    assert summary["gateway_savings_fully_measured"] is True


def test_paritok_usage_headers_require_a_complete_non_negative_measurement() -> None:
    assert qwen._paritok_usage_from_headers(
        {
            "x-paritok-input-tokens-original": "120",
            "x-paritok-input-tokens-compressed": "75",
            "x-paritok-tokens-saved": "45",
        }
    ) == {
        "input_tokens_original": 120,
        "input_tokens_compressed": 75,
        "tokens_saved": 45,
    }
    assert qwen._paritok_usage_from_headers({"x-paritok-input-tokens-original": "120"}) == {}


def test_paritok_raw_response_headers_reach_the_usage_ledger(
    usage_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del usage_database

    class RawCompletion:
        headers = {
            "x-paritok-input-tokens-original": "90",
            "x-paritok-input-tokens-compressed": "55",
            "x-paritok-tokens-saved": "35",
        }

        @staticmethod
        def parse() -> dict[str, object]:
            return {
                "model": "test-model",
                "choices": [{"message": {"content": "answer"}, "finish_reason": "stop"}],
                "usage": {"input_tokens": 65, "output_tokens": 4},
            }

    raw_accessor = SimpleNamespace(create=lambda **_payload: RawCompletion())
    completions = SimpleNamespace(with_raw_response=raw_accessor)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    monkeypatch.setattr(qwen, "_create_openai_client", lambda _timeout: client)

    with llm_usage_context(
        run_id="run-raw-paritok",
        workspace_id=LEGACY_WORKSPACE_ID,
        component="agent",
    ):
        qwen.call_llm_chat(
            [{"role": "user", "content": "prompt"}],
            model="test-model",
            gateway="paritok",
        )

    summary = summarize_llm_usage_run("run-raw-paritok")
    assert summary["gateway_input_tokens_original"] == 90
    assert summary["gateway_input_tokens_compressed"] == 55
    assert summary["gateway_tokens_saved"] == 35
    assert summary["gateway_savings_fully_measured"] is True


def test_paritok_rejects_an_upstream_provider_mismatch(
    usage_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del usage_database
    monkeypatch.setenv(qwen.PARITOK_UPSTREAM_PROFILE_ENV, "deepseek")

    with pytest.raises(qwen.LLMConfigurationError, match="does not match"):
        qwen.call_llm_chat(
            [{"role": "user", "content": "hello"}],
            model="test-model",
            provider="gemini",
            gateway="paritok",
        )
