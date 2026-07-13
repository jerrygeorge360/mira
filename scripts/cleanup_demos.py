"""Delete expired disposable demo workspaces and their vector pointers."""

from __future__ import annotations

from dotenv import load_dotenv

from core.demo import cleanup_expired_demo_workspaces


def main() -> int:
    load_dotenv()
    cleaned = cleanup_expired_demo_workspaces()
    print(f"cleaned demo workspaces: {cleaned}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
