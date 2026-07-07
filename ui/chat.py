"""Interactive chat UI surface for mocked or real MIRA agent sessions.

Ownership: MIRA contributors.
Related issue: ISSUE-044.
Architecture area: UI.
"""

from __future__ import annotations

import importlib
from typing import Any, Protocol, cast

ChatMessage = dict[str, object]
AgentResponse = dict[str, object]

CHAT_MESSAGES_KEY = "mira_chat_messages"
CHAT_META_KEY = "mira_chat_meta"
ACTIVE_CONSTRAINTS_KEY = "mira_active_constraints"

DEFAULT_SESSION_ID = "demo-session"
DEFAULT_RETRIEVAL_MODE = "quick"
DEFAULT_CONSTRAINTS = (
    "Use 2026 for MIRA project dates.",
    "Run make check before PR handoff.",
)


class ChatAgent(Protocol):
    """Small UI-facing agent protocol shared by mock and real agents."""

    def respond(self, user_message: str) -> AgentResponse:
        """Return a structured response for one user message."""


class MockChatAgent:
    """Deterministic mocked agent for UI development before backend wiring."""

    def respond(self, user_message: str) -> AgentResponse:
        """Return a predictable demo response without touching backend memory."""
        retrieval_mode = _mock_retrieval_mode(user_message)
        return {
            "answer": f"Mock MIRA heard: {user_message}",
            "retrieval_mode": retrieval_mode,
            "used_session_items": ["mock_sws_2026"],
            "active_constraints": list(DEFAULT_CONSTRAINTS),
        }


def render_chat(
    session_id: str = DEFAULT_SESSION_ID,
    st: Any | None = None,
    agent: ChatAgent | None = None,
    *,
    use_mock: bool = True,
) -> None:
    """Render the chat page and process one submitted user message."""
    streamlit = st if st is not None else _load_streamlit()
    chat_agent = agent or _default_agent(session_id, use_mock)
    state = _session_state(streamlit)
    _ensure_chat_state(state)

    streamlit.title("💬 Chat")
    streamlit.caption("Send a message to MIRA and inspect retrieval/session-memory signals.")

    _render_status(streamlit, state)
    _render_messages(streamlit, state)

    user_message = _chat_input(streamlit)
    if not user_message:
        return

    _append_message(state, "user", user_message)
    response = chat_agent.respond(user_message)
    _append_message(state, "assistant", _answer(response))
    _update_chat_meta(state, response)
    _render_latest_exchange(streamlit, user_message, response)
    _render_status(streamlit, state)


def _default_agent(session_id: str, use_mock: bool) -> ChatAgent:
    if use_mock:
        return MockChatAgent()
    module = importlib.import_module("core.agent")
    agent_class = module.Agent
    return cast(ChatAgent, agent_class(session_id))


def _render_status(st: Any, state: dict[str, object]) -> None:
    meta = _meta(state)
    constraints = _constraints(state)
    retrieval_mode = str(meta.get("retrieval_mode", DEFAULT_RETRIEVAL_MODE))
    sws_updated = bool(meta.get("sws_updated", False))
    st.markdown(f"**Retrieval mode:** `{retrieval_mode}`")
    st.markdown(f"**Session Working Set updated:** {'yes' if sws_updated else 'not yet'}")
    st.markdown("**Active constraints:**")
    for constraint in constraints:
        st.markdown(f"- {constraint}")


def _render_messages(st: Any, state: dict[str, object]) -> None:
    for message in _messages(state):
        role = str(message["role"]).title()
        st.markdown(f"**{role}:** {message['content']}")


def _render_latest_exchange(st: Any, user_message: str, response: AgentResponse) -> None:
    st.markdown(f"**User:** {user_message}")
    st.markdown(f"**Assistant:** {_answer(response)}")


def _chat_input(st: Any) -> str | None:
    chat_input = getattr(st, "chat_input", None)
    if callable(chat_input):
        value = chat_input("Message MIRA")
        return value.strip() if isinstance(value, str) and value.strip() else None
    text_input = getattr(st, "text_input", None)
    if callable(text_input):
        value = text_input("Message MIRA")
        return value.strip() if isinstance(value, str) and value.strip() else None
    return None


def _session_state(st: Any) -> dict[str, object]:
    state = getattr(st, "session_state", None)
    if isinstance(state, dict):
        return state
    state = {}
    st.session_state = state
    return state


def _ensure_chat_state(state: dict[str, object]) -> None:
    state.setdefault(CHAT_MESSAGES_KEY, [])
    state.setdefault(
        CHAT_META_KEY,
        {
            "retrieval_mode": DEFAULT_RETRIEVAL_MODE,
            "sws_updated": False,
        },
    )
    state.setdefault(ACTIVE_CONSTRAINTS_KEY, list(DEFAULT_CONSTRAINTS))


def _append_message(state: dict[str, object], role: str, content: str) -> None:
    _messages(state).append({"role": role, "content": content})


def _update_chat_meta(state: dict[str, object], response: AgentResponse) -> None:
    used_session_items = response.get("used_session_items", [])
    state[CHAT_META_KEY] = {
        "retrieval_mode": str(response.get("retrieval_mode", DEFAULT_RETRIEVAL_MODE)),
        "sws_updated": bool(_object_list(used_session_items)),
    }
    constraints = _object_list(response.get("active_constraints"))
    if constraints:
        state[ACTIVE_CONSTRAINTS_KEY] = [str(constraint) for constraint in constraints]


def _messages(state: dict[str, object]) -> list[ChatMessage]:
    messages = state.get(CHAT_MESSAGES_KEY)
    if isinstance(messages, list):
        return messages
    state[CHAT_MESSAGES_KEY] = []
    return state[CHAT_MESSAGES_KEY]  # type: ignore[return-value]


def _meta(state: dict[str, object]) -> dict[str, object]:
    meta = state.get(CHAT_META_KEY)
    if isinstance(meta, dict):
        return meta
    state[CHAT_META_KEY] = {}
    return state[CHAT_META_KEY]  # type: ignore[return-value]


def _constraints(state: dict[str, object]) -> list[str]:
    constraints = _object_list(state.get(ACTIVE_CONSTRAINTS_KEY))
    return [str(constraint) for constraint in constraints]


def _object_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _answer(response: AgentResponse) -> str:
    answer = response.get("answer", "")
    return str(answer).strip() or "(No response.)"


def _mock_retrieval_mode(user_message: str) -> str:
    normalized = user_message.casefold()
    if any(marker in normalized for marker in ("why", "changed", "switch", "contradict")):
        return "relational"
    if any(marker in normalized for marker in ("summarize", "pattern", "history")):
        return "deep"
    return DEFAULT_RETRIEVAL_MODE


def _load_streamlit() -> Any:
    try:
        return importlib.import_module("streamlit")
    except ModuleNotFoundError as error:  # pragma: no cover - exercised only without streamlit
        raise RuntimeError("streamlit is not installed; install it to run chat UI") from error
