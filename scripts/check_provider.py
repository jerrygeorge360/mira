"""Smoke-check configured chat and embedding providers.

This script is intentionally tiny and explicit: it verifies that the current
``.env`` can make one structured chat call and one embedding call before a
worker or benchmark spends real time and money.
"""

from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

from core.llm import embeddings
from core.llm.qwen import DASHSCOPE_API_KEY_ENV, LLM_API_KEY_ENV, LLMClientError, call_llm_json


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = _parse_args(argv)
    try:
        if args.chat:
            _check_chat()
        if args.embeddings:
            _check_embeddings(require_live=args.require_live_embeddings)
    except (LLMClientError, ValueError) as error:
        print(f"provider check failed: {error}", file=sys.stderr)
        return 2
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chat", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--embeddings", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--require-live-embeddings",
        action="store_true",
        help="Fail if embeddings are configured to use deterministic local fallback.",
    )
    return parser.parse_args(argv)


def _check_chat() -> None:
    response = call_llm_json(
        [
            {
                "role": "user",
                "content": "Extract no facts from this provider smoke test.",
            }
        ],
        schema_name="atomic_fact_extraction",
        timeout_s=30,
    )
    payload = response.get("json")
    if not isinstance(payload, dict) or "facts" not in payload:
        raise ValueError("chat provider did not return the expected structured payload")
    print(
        "chat ok "
        f"provider={response.get('provider')} "
        f"model={response.get('model')} "
        f"schema={response.get('schema_name')}"
    )


def _check_embeddings(*, require_live: bool) -> None:
    mode = os.environ.get(embeddings.EMBEDDING_MODE_ENV, embeddings.DEFAULT_EMBEDDING_MODE)
    has_credentials = bool(
        os.environ.get(embeddings.EMBEDDING_API_KEY_ENV)
        or os.environ.get(LLM_API_KEY_ENV)
        or os.environ.get(DASHSCOPE_API_KEY_ENV)
    )
    mode = mode.casefold()
    using_deterministic = mode == "deterministic" or (mode == "auto" and not has_credentials)
    if require_live and using_deterministic:
        raise ValueError("embeddings are using deterministic fallback, not a live provider")

    vector = embeddings.embed_text("MIRA provider smoke test", timeout_s=30)
    source = _embedding_source(mode, using_deterministic)
    model = (
        os.environ.get(
            embeddings.LOCAL_EMBEDDING_MODEL_ENV,
            embeddings.DEFAULT_LOCAL_EMBEDDING_MODEL,
        )
        if source == "local"
        else os.environ.get(embeddings.EMBEDDING_MODEL_ENV, embeddings.DEFAULT_EMBEDDING_MODEL)
    )
    print(f"embeddings ok source={source} model={model} dimensions={len(vector)}")


def _embedding_source(mode: str, using_deterministic: bool) -> str:
    if using_deterministic:
        return "deterministic"
    if mode == "local":
        return "local"
    return "provider"


if __name__ == "__main__":
    raise SystemExit(main())
