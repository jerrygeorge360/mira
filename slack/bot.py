"""Slack bot for MIRA: Socket Mode, thread-based sessions, Block Kit responses.

Ownership: Kelechi.
Related issue: ISSUE-701.
Architecture area: Slack.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from core.agent import handle_user_message as agent_handle_message
from core.db.repositories import configure_database, repository_connection

LOGGER = logging.getLogger(__name__)

SESSION_TTL_MINUTES = int(os.environ.get("MIRA_SESSION_TTL_MINUTES", "120"))


def build_session_id(channel_id: str, thread_ts: str | None, user_id: str) -> str:
    """Derive a deterministic MIRA session ID from Slack context.

    All messages from the same user in a channel share one session so
    cross-thread context (e.g. "continue where we left off") works.
    """
    return f"slack:{channel_id}:user:{user_id}"


def _ensure_session(session_id: str, user_id: str) -> str:
    """Create the MIRA session if it doesn't already exist."""
    now = datetime.now(timezone.utc).isoformat()  # noqa: UP017
    with repository_connection() as connection:
        existing = connection.execute(
            "SELECT id FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if existing is None:
            connection.execute(
                "INSERT INTO sessions (id, user_id, status, created_at, updated_at) "
                "VALUES (?, ?, 'active', ?, ?)",
                (session_id, user_id, now, now),
            )
    return session_id


def build_answer_blocks(answer: str, retrieval_mode: str, trace_id: str) -> list[dict[str, object]]:
    """Build Slack Block Kit blocks for a MIRA response."""
    blocks: list[dict[str, object]] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": answer}},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Mode: `{retrieval_mode}`  ·  Trace: `{trace_id[:8]}`",
                }
            ],
        },
    ]
    return blocks


def build_error_blocks(error_message: str) -> list[dict[str, object]]:
    """Build Slack Block Kit blocks for an error response."""
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"Sorry, something went wrong: {error_message}",
            },
        }
    ]


def handle_message(
    channel_id: str, user_id: str, text: str, thread_ts: str | None = None
) -> dict[str, object]:
    """Process a Slack message through MIRA and return response data."""
    if not text.strip():
        raise ValueError("message text must not be empty")

    session_id = build_session_id(channel_id, thread_ts, user_id)
    _ensure_session(session_id, user_id)

    response = agent_handle_message(session_id, text)

    return {
        "answer": str(response["answer"]),
        "retrieval_mode": str(response["retrieval_mode"]),
        "trace_id": str(response["trace_id"]),
        "session_id": session_id,
    }


def run_bot() -> None:
    """Start the MIRA Slack bot with Socket Mode."""
    try:
        from dotenv import load_dotenv

        loaded = load_dotenv()
        LOGGER.info(
            "Loaded .env: %s (DASHSCOPE_API_KEY present: %s)",
            loaded,
            "DASHSCOPE_API_KEY" in os.environ,
        )
    except ImportError:
        LOGGER.warning("python-dotenv not installed, .env will not be loaded")

    db_path = os.environ.get("MIRA_DB_PATH", "./mira.db")
    configure_database(db_path)

    bot_token = os.environ.get("SLACK_BOT_TOKEN")
    app_token = os.environ.get("SLACK_APP_TOKEN")

    if not bot_token:
        raise ValueError("SLACK_BOT_TOKEN environment variable is required")
    if not app_token:
        raise ValueError("SLACK_APP_TOKEN environment variable is required")

    from slack_bolt import App
    from slack_bolt.adapter.socket_mode import SocketModeHandler

    app = App(token=bot_token)

    @app.message("")  # type: ignore[misc, untyped-decorator, unused-ignore]
    def on_message(message: dict[str, object], say: Callable[..., Any]) -> None:
        subtype = message.get("subtype", "")
        if subtype in ("message_deleted", "message_changed"):
            return
        bot_id = str(message.get("bot_id", ""))
        if bot_id:
            return

        channel_id = str(message.get("channel", ""))
        user_id = str(message.get("user", ""))
        text = str(message.get("text", ""))
        thread_ts: str | None = message.get("thread_ts") or message.get("ts")  # type: ignore[assignment]

        if not user_id or not text.strip():
            return

        LOGGER.info("Slack message from %s in %s", user_id, channel_id)

        try:
            result = handle_message(channel_id, user_id, text, thread_ts)
            answer = str(result["answer"])
            retrieval_mode = str(result["retrieval_mode"])
            trace_id = str(result["trace_id"])
            blocks = build_answer_blocks(answer, retrieval_mode, trace_id)
            say(text=answer, blocks=blocks, thread_ts=thread_ts)
        except Exception:
            LOGGER.exception("Error handling Slack message")
            say(
                text="MIRA encountered an internal error.",
                blocks=build_error_blocks("MIRA encountered an internal error."),
                thread_ts=thread_ts,
            )

    handler = SocketModeHandler(app, app_token)
    LOGGER.info("Starting MIRA Slack bot in Socket Mode")
    handler.start()  # type: ignore[no-untyped-call, unused-ignore]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("slack_bolt").setLevel(logging.WARNING)
    run_bot()
