"""Print slow-path queue and memory-ingestion health."""

from __future__ import annotations

import argparse
import json

from dotenv import load_dotenv

from core.memory.slow_path import get_slow_path_health


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = _parse_args(argv)
    print(json.dumps(get_slow_path_health(limit=args.limit), indent=2, sort_keys=True, default=str))
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=10, help="Number of recent failures to show.")
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
