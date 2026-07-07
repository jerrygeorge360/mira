"""Download and convert the official LongMemEval data into MIRA's benchmark format.

Ownership: MIRA contributors.
Related issue: ISSUE-123.
Architecture area: evaluation.

This script downloads one of the official LongMemEval JSON files, rewrites it into the
repo-native format expected by ``evaluation.longmemeval``, and saves the result under
``data/benchmarks/`` by default.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import cast

DEFAULT_OUT_DIR = Path("data/benchmarks")
DEFAULT_OUT_NAME = "longmemeval.json"

LONGMEMEVAL_URLS: dict[str, str] = {
    "oracle": "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_oracle.json",
    "s": "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json",
    "m": "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_m_cleaned.json",
}


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    args = _parse_args(argv)
    source = _download_json(args.variant, args.download_dir)
    converted = convert_longmemeval_dataset(source)
    converted_examples = cast(list[dict[str, object]], converted["examples"])
    args.out_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.out_dir / args.out_name
    output_path.write_text(json.dumps(converted, indent=2, ensure_ascii=True), encoding="utf-8")
    print(f"saved {len(converted_examples)} examples to {output_path}")
    return 0


def download_longmemeval(variant: str, download_dir: Path) -> Path:
    """Download one LongMemEval source file and return the local path."""
    if variant not in LONGMEMEVAL_URLS:
        allowed = ", ".join(sorted(LONGMEMEVAL_URLS))
        raise ValueError(f"unknown variant {variant!r}; expected one of: {allowed}")
    download_dir.mkdir(parents=True, exist_ok=True)
    output_path = download_dir / f"longmemeval_{variant}.json"
    if output_path.exists():
        return output_path
    request = urllib.request.Request(
        LONGMEMEVAL_URLS[variant],
        headers={"User-Agent": "Mozilla/5.0"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=120) as response:  # nosec B310
        payload = response.read()
    output_path.write_bytes(payload)
    return output_path


def convert_longmemeval_dataset(
    source: Path | str | dict[str, object] | list[object],
) -> dict[str, object]:
    """Convert the official LongMemEval schema to the repo-native benchmark schema."""
    if isinstance(source, (dict, list)):
        data = source
    else:
        data = json.loads(Path(source).read_text(encoding="utf-8"))

    if isinstance(data, list):
        examples = data
    elif isinstance(data, dict):
        raw_examples = data.get("cases")
        if not isinstance(raw_examples, list):
            raw_examples = data.get("examples")
        examples = raw_examples if isinstance(raw_examples, list) else []
    else:
        examples = []

    converted_examples: list[dict[str, object]] = []
    for index, raw_example in enumerate(examples):
        if not isinstance(raw_example, dict):
            continue
        converted_examples.append(_convert_example(raw_example, index))

    name = str(data.get("name", "longmemeval")) if isinstance(data, dict) else "longmemeval"
    return {"name": f"{name}-mira", "examples": converted_examples}


def _convert_example(raw_example: dict[str, object], index: int) -> dict[str, object]:
    question_id = str(raw_example.get("question_id", f"lme-{index + 1:04d}"))
    question_type = str(raw_example.get("question_type", "unspecified"))
    question = str(raw_example.get("question", "")).strip()
    answer = str(raw_example.get("answer", "")).strip()
    sessions = _convert_sessions(raw_example)
    return {
        "question_id": question_id,
        "question_type": question_type,
        "question": question,
        "answer": answer,
        "sessions": sessions,
    }


def _convert_sessions(raw_example: dict[str, object]) -> list[dict[str, object]]:
    raw_sessions = raw_example.get("haystack_sessions")
    if not isinstance(raw_sessions, list):
        raw_sessions = raw_example.get("sessions", [])
    if not isinstance(raw_sessions, list):
        return []

    sessions: list[dict[str, object]] = []
    for index, raw_session in enumerate(raw_sessions):
        if not isinstance(raw_session, list):
            continue
        session_id = _session_id(raw_example, index)
        turns: list[dict[str, str]] = []
        for raw_turn in raw_session:
            if not isinstance(raw_turn, dict):
                continue
            role = str(raw_turn.get("role", "")).strip()
            content = str(raw_turn.get("content", "")).strip()
            if role and content:
                turns.append({"role": role, "content": content})
        if turns:
            sessions.append({"session_id": session_id, "turns": turns})
    return sessions


def _session_id(raw_example: dict[str, object], index: int) -> str:
    raw_ids = raw_example.get("haystack_session_ids")
    if isinstance(raw_ids, list) and index < len(raw_ids):
        return str(raw_ids[index])
    return f"session_{index + 1}"


def _download_json(variant: str, download_dir: Path) -> dict[str, object]:
    path = download_longmemeval(variant, download_dir)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("downloaded LongMemEval file must be a JSON object")
    return cast(dict[str, object], data)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="prepare_longmemeval",
        description="Download and convert LongMemEval into MIRA's benchmark format.",
    )
    parser.add_argument(
        "--variant",
        default="oracle",
        choices=sorted(LONGMEMEVAL_URLS),
        help="LongMemEval file to download.",
    )
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=Path("data/raw/longmemeval"),
        help="Where the downloaded official JSON should be cached.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="Directory where the converted dataset will be saved.",
    )
    parser.add_argument(
        "--out-name",
        default=DEFAULT_OUT_NAME,
        help="Filename for the converted dataset.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":  # pragma: no cover - module entry point
    sys.exit(main())
