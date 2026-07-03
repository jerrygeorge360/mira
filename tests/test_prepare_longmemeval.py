"""Verify the LongMemEval download/conversion helper."""

from __future__ import annotations

from scripts.prepare_longmemeval import convert_longmemeval_dataset


def test_convert_longmemeval_dataset_rewrites_haystack_sessions() -> None:
    """Official LongMemEval sessions are rewritten into repo-native benchmark sessions."""
    source = {
        "name": "longmemeval-oracle",
        "cases": [
            {
                "question_id": "q-1",
                "question_type": "multi-session",
                "question": "What database do I use now?",
                "answer": "PostgreSQL",
                "haystack_session_ids": ["s1", "s2"],
                "haystack_sessions": [
                    [
                        {"role": "user", "content": "We used MongoDB before."},
                        {"role": "assistant", "content": "Okay."},
                    ],
                    [
                        {"role": "user", "content": "We switched to PostgreSQL."},
                    ],
                ],
            }
        ],
    }

    converted = convert_longmemeval_dataset(source)

    assert converted["name"] == "longmemeval-oracle-mira"
    example = converted["examples"][0]
    assert example["question_id"] == "q-1"
    assert example["question_type"] == "multi-session"
    assert example["question"] == "What database do I use now?"
    assert example["answer"] == "PostgreSQL"
    assert [session["session_id"] for session in example["sessions"]] == ["s1", "s2"]
    assert example["sessions"][0]["turns"][0] == {
        "role": "user",
        "content": "We used MongoDB before.",
    }


def test_convert_longmemeval_dataset_accepts_bare_list() -> None:
    """The converter accepts the list-shaped upstream LongMemEval exports."""
    source = [
        {
            "question_id": "q-2",
            "question_type": "single-session-user",
            "question": "What database do I use now?",
            "answer": "PostgreSQL",
            "haystack_sessions": [
                [{"role": "user", "content": "We switched to PostgreSQL."}],
            ],
        }
    ]

    converted = convert_longmemeval_dataset(source)

    assert converted["name"] == "longmemeval-mira"
    assert converted["examples"][0]["sessions"][0]["session_id"] == "session_1"
