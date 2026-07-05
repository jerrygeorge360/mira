"""Inspect the durable memory graph as a provenance-friendly JSON snapshot."""

from __future__ import annotations

import argparse
import json

from dotenv import load_dotenv

from core.memory.graph import inspect_memory_graph


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = _parse_args(argv)
    snapshot = inspect_memory_graph(entity=args.entity, limit=args.limit)
    print(json.dumps(snapshot, indent=2, sort_keys=True))
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entity", help="Filter graph nodes by label substring.")
    parser.add_argument("--limit", type=int, default=50, help="Maximum nodes and edges to return.")
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
