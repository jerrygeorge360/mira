"""Verify ISSUE-044 chat UI interactions.

Ownership: MIRA contributors.
Related issue: ISSUE-044.
Architecture area: UI.
"""

from __future__ import annotations

from typing import Any

from ui.chat import (
    ACTIVE_CONSTRAINTS_KEY,
    CHAT_MESSAGES_KEY,
    CHAT_META_KEY,
    MockChatAgent,
    render_chat,
)


class _FakeStreamlit:
    """Small Streamlit stand-in for exercising chat UI without Streamlit."""

    def __init__(self, message: str | None = None) -> None:
        self.session_state: dict[str, object] = {}
        self.calls: list[tuple[str, Any]] = []
        self._message = message

    def title(self, text: str) -> None:
        self.calls.append(("title", text))

    def caption(self, text: str) -> None:
        self.calls.append(("caption", text))

    def markdown(self, text: str) -> None:
        self.calls.append(("markdown", text))

    def chat_input(self, label: str) -> str | None:
        self.calls.append(("chat_input", label))
        return self._message


class _InjectedAgent:
    """Agent double representing the real agent adapter boundary."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def respond(self, user_message: str) -> dict[str, object]:
        self.messages.append(user_message)
        return {
            "answer": "Real-ish response.",
            "retrieval_mode": "deep",
            "used_session_items": ["sws_real"],
            "active_constraints": ["Respect the current branch."],
        }


def test_user_can_send_message() -> None:
    """Submitting chat input stores the user message."""
    fake = _FakeStreamlit(message="Use Rust now.")

    render_chat(st=fake, agent=MockChatAgent())

    messages = fake.session_state[CHAT_MESSAGES_KEY]
    assert isinstance(messages, list)
    assert messages[0] == {"role": "user", "content": "Use Rust now."}


def test_response_displays() -> None:
    """The assistant response is stored and rendered."""
    fake = _FakeStreamlit(message="Hello MIRA.")

    render_chat(st=fake, agent=MockChatAgent())

    rendered = _rendered_markdown(fake)
    assert "Assistant" in rendered
    assert "Mock MIRA heard: Hello MIRA." in rendered


def test_retrieval_mode_visible() -> None:
    """Chat status shows the retrieval mode returned by the agent."""
    fake = _FakeStreamlit(message="Why did I switch databases?")

    render_chat(st=fake, agent=MockChatAgent())

    meta = fake.session_state[CHAT_META_KEY]
    assert isinstance(meta, dict)
    assert meta["retrieval_mode"] == "relational"
    assert "`relational`" in _rendered_markdown(fake)


def test_sws_updates_visible() -> None:
    """Using session items sets the Session Working Set update indicator."""
    fake = _FakeStreamlit(message="Use 2026.")

    render_chat(st=fake, agent=MockChatAgent())

    meta = fake.session_state[CHAT_META_KEY]
    assert isinstance(meta, dict)
    assert meta["sws_updated"] is True
    assert "Session Working Set updated:** yes" in _rendered_markdown(fake)


def test_active_constraints_summary_visible() -> None:
    """The chat page summarizes active constraints for the demo flow."""
    fake = _FakeStreamlit(message="Continue.")

    render_chat(st=fake, agent=MockChatAgent())

    constraints = fake.session_state[ACTIVE_CONSTRAINTS_KEY]
    assert isinstance(constraints, list)
    assert "Run make check before PR handoff." in constraints
    assert "Active constraints" in _rendered_markdown(fake)


def test_injected_real_agent_boundary_works() -> None:
    """The UI can use an injected real-agent-compatible object."""
    fake = _FakeStreamlit(message="What do you remember?")
    agent = _InjectedAgent()

    render_chat("real_session", st=fake, agent=agent, use_mock=False)

    assert agent.messages == ["What do you remember?"]
    assert "Real-ish response." in _rendered_markdown(fake)
    assert "Respect the current branch." in fake.session_state[ACTIVE_CONSTRAINTS_KEY]


def _rendered_markdown(fake: _FakeStreamlit) -> str:
    return "\n".join(str(value) for name, value in fake.calls if name == "markdown")
