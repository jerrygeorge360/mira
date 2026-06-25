"""Tests for the MIRA Slack bot.

Ownership: Kelechi.
Related issue: ISSUE-701.
Architecture area: Slack.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("slack_bolt")

import slack_bolt  # noqa: F401 — ensure module exists for monkeypatch

from core.db.repositories import configure_database, repository_connection
from slack.bot import (
    _ensure_session,
    build_answer_blocks,
    build_error_blocks,
    build_session_id,
    handle_message,
)


@pytest.fixture
def database_path(tmp_path: Path) -> Iterator[Path]:
    path = tmp_path / "mira.sqlite3"
    configure_database(path)
    yield path


# --- build_session_id ---


class TestBuildSessionId:
    def test_session_id_format(self) -> None:
        result = build_session_id("C123", "1712345678.000001", "U456")
        assert result == "slack:C123:user:U456"

    def test_channel_message_same_session(self) -> None:
        result = build_session_id("C123", None, "U456")
        assert result == "slack:C123:user:U456"

    def test_different_users_different_sessions(self) -> None:
        session_a = build_session_id("C123", None, "U456")
        session_b = build_session_id("C123", None, "U789")
        assert session_a != session_b

    def test_thread_same_session_as_channel(self) -> None:
        session_a = build_session_id("C123", "1712345678.000001", "U456")
        session_b = build_session_id("C123", None, "U456")
        assert session_a == session_b


# --- _ensure_session ---


class TestEnsureSession:
    def test_creates_new_session(self, database_path: Path) -> None:
        session_id = _ensure_session("test-sid", "test-user")
        with repository_connection() as conn:
            row = conn.execute(
                "SELECT id, user_id, status FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        assert row is not None
        assert row["id"] == "test-sid"
        assert row["user_id"] == "test-user"
        assert row["status"] == "active"

    def test_idempotent_when_session_exists(self, database_path: Path) -> None:
        _ensure_session("test-sid", "test-user")
        _ensure_session("test-sid", "other-user")
        with repository_connection() as conn:
            rows = conn.execute(
                "SELECT id, user_id FROM sessions WHERE id = ?", ("test-sid",)
            ).fetchall()
        assert len(rows) == 1
        assert rows[0]["user_id"] == "test-user"


# --- build_answer_blocks / build_error_blocks ---


class TestBlockBuilders:
    def test_answer_blocks_structure(self) -> None:
        blocks = build_answer_blocks("Hello!", "quick", "abc123def456")
        assert len(blocks) == 2
        assert blocks[0]["type"] == "section"
        assert blocks[0]["text"]["text"] == "Hello!"
        assert blocks[1]["type"] == "context"
        assert "`quick`" in str(blocks[1]["elements"][0]["text"])
        assert "`abc123de`" in str(blocks[1]["elements"][0]["text"])

    def test_answer_blocks_empty_answer(self) -> None:
        blocks = build_answer_blocks("", "auto", "abcdef00")
        assert blocks[0]["text"]["text"] == ""

    def test_error_blocks(self) -> None:
        blocks = build_error_blocks("token expired")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "section"
        assert "token expired" in str(blocks[0]["text"]["text"])


# --- handle_message (with mocked agent_handle_user_message) ---


def _mock_handle_user_message(
    monkeypatch: pytest.MonkeyPatch,
    answer: str = "Hello from MIRA",
    retrieval_mode: str = "quick",
    trace_id: str = "trace001",
) -> None:
    import slack.bot as bot_module

    def fake(session_id: str, user_message: str) -> dict[str, object]:
        return {
            "answer": answer,
            "retrieval_mode": retrieval_mode,
            "trace_id": trace_id,
            "session_id": session_id,
            "user_observation_id": "obs-001",
            "assistant_observation_id": "obs-002",
            "used_session_items": [],
            "used_memory_items": [],
        }

    monkeypatch.setattr(bot_module, "agent_handle_message", fake)


class TestHandleMessage:
    def test_basic_message(self, database_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_handle_user_message(monkeypatch)
        result = handle_message("C123", "U456", "hello", None)
        assert result["answer"] == "Hello from MIRA"
        assert result["retrieval_mode"] == "quick"
        assert result["trace_id"] == "trace001"
        assert result["session_id"] == "slack:C123:user:U456"

    def test_thread_message(self, database_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_handle_user_message(monkeypatch)
        result = handle_message("C123", "U456", "reply", "1712345678.000001")
        assert result["session_id"] == "slack:C123:user:U456"

    def test_creates_session(self, database_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_handle_user_message(monkeypatch)
        handle_message("C999", "U777", "first message", None)
        session_id = "slack:C999:user:U777"
        with repository_connection() as conn:
            row = conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
        assert row is not None

    def test_handles_long_text(self, database_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_handle_user_message(monkeypatch, answer="A" * 5000)
        result = handle_message("C1", "U1", "tell me a story", None)
        assert len(str(result["answer"])) == 5000

    def test_empty_text_raises(self, database_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_handle_user_message(monkeypatch)
        with pytest.raises(ValueError):
            handle_message("C1", "U1", "   ", None)

    def test_integration_with_agent(
        self, database_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify handle_message calls through to the real agent module."""
        import core.agent as agent_module

        fake_responses: list[dict[str, object]] = []
        original = agent_module.handle_user_message

        def capturing(session_id: str, user_msg: str) -> dict[str, object]:
            result = original(session_id, user_msg)
            fake_responses.append(result)
            return result

        def fake_qwen_call(*a: Any, **kw: Any) -> dict[str, object]:
            return {"json": {"answer": "ok"}}

        monkeypatch.setattr(agent_module, "call_qwen_json", fake_qwen_call)
        monkeypatch.setattr(agent_module, "handle_user_message", capturing)

        result = handle_message("C1", "U1", "hi", None)
        assert result["answer"] == "ok"
        assert result["session_id"] == "slack:C1:user:U1"


# --- run_bot (mocked Slack Bolt) ---


class TestRunBot:
    def _stub_dotenv_and_db(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Prevent run_bot from actually loading .env or touching the database."""
        monkeypatch.setattr("dotenv.load_dotenv", lambda: True)
        monkeypatch.setattr("slack.bot.configure_database", lambda _path: None)

    def test_missing_bot_token_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._stub_dotenv_and_db(monkeypatch)
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        monkeypatch.delenv("SLACK_APP_TOKEN", raising=False)
        from slack.bot import run_bot

        with pytest.raises(ValueError, match="SLACK_BOT_TOKEN"):
            run_bot()

    def test_missing_app_token_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._stub_dotenv_and_db(monkeypatch)
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-valid")
        monkeypatch.delenv("SLACK_APP_TOKEN", raising=False)
        from slack.bot import run_bot

        with pytest.raises(ValueError, match="SLACK_APP_TOKEN"):
            run_bot()

    def test_handler_registration_and_invocation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._stub_dotenv_and_db(monkeypatch)
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
        monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")

        captured_handler: list[Callable[..., Any]] = []
        captured_say_kwargs: list[dict[str, object]] = []

        class MockApp:
            def message(self, pattern: str) -> Callable[..., Any]:
                def decorator(handler: Callable[..., Any]) -> Callable[..., Any]:
                    captured_handler.append(handler)
                    return handler

                return decorator

            def event(self, *args: Any, **kwargs: Any) -> Callable[..., Any]:
                return lambda f: f

        class MockSocketModeHandler:
            def __init__(self, _app: object, _token: str) -> None:
                pass

            def start(self) -> None:
                pass

        monkeypatch.setattr("slack_bolt.App", lambda **kw: MockApp())
        monkeypatch.setattr(
            "slack_bolt.adapter.socket_mode.SocketModeHandler", MockSocketModeHandler
        )

        _mock_handle_user_message(
            monkeypatch, answer="bot reply", retrieval_mode="deep", trace_id="tr999"
        )

        from slack.bot import run_bot

        run_bot()

        assert len(captured_handler) == 1
        handler = captured_handler[0]

        fake_message: dict[str, object] = {
            "channel": "C001",
            "user": "U001",
            "text": "test message",
            "ts": "1712345678.000001",
            "type": "message",
        }

        def recording_say(**kwargs: Any) -> None:
            captured_say_kwargs.append(kwargs)

        handler(fake_message, recording_say)

        assert len(captured_say_kwargs) == 1
        say_kwargs = captured_say_kwargs[0]
        assert str(say_kwargs["text"]) == "bot reply"
        assert len(say_kwargs["blocks"]) == 2
        assert say_kwargs["thread_ts"] == "1712345678.000001"

    def test_ignores_bot_messages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._stub_dotenv_and_db(monkeypatch)
        from slack import bot as bot_module

        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
        monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")

        captured_handler: list[Callable[..., Any]] = []

        class MockApp:
            def message(self, pattern: str) -> Callable[..., Any]:
                def decorator(handler: Callable[..., Any]) -> Callable[..., Any]:
                    captured_handler.append(handler)
                    return handler

                return decorator

            def event(self, *args: Any, **kwargs: Any) -> Callable[..., Any]:
                return lambda f: f

        class MockSocketModeHandler:
            def __init__(self, _app: object, _token: str) -> None:
                pass

            def start(self) -> None:
                pass

        monkeypatch.setattr("slack_bolt.App", lambda **kw: MockApp())
        monkeypatch.setattr(
            "slack_bolt.adapter.socket_mode.SocketModeHandler", MockSocketModeHandler
        )

        called: list[bool] = []

        def _should_not_be_called(*args: Any, **kwargs: Any) -> None:
            called.append(True)

        monkeypatch.setattr(bot_module, "handle_message", _should_not_be_called)

        from slack.bot import run_bot

        run_bot()

        handler = captured_handler[0]
        fake_bot_message: dict[str, object] = {
            "channel": "C001",
            "user": "U001",
            "text": "I am a bot",
            "bot_id": "B001",
            "ts": "1712345678.000002",
        }
        handler(fake_bot_message, lambda **kw: None)

        assert not called
