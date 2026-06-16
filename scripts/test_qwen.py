"""Manual smoke check for the Qwen client.

Developer convenience script: sends a single prompt through the Qwen client to
verify DASHSCOPE_API_KEY and connectivity. Not part of the automated suite.

Run with: python scripts/test_qwen.py

ISSUE-002: Qwen connectivity check.
"""

from __future__ import annotations


def main() -> None:
    """Send a single test prompt through the Qwen client and print the reply."""
    raise NotImplementedError


if __name__ == "__main__":
    main()
