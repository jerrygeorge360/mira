"""Search MIRA vector memory and show the SQLite records behind Chroma pointers."""

from __future__ import annotations

import argparse
import json

from dotenv import load_dotenv

from core.db import chroma
from core.db.repositories import repository_connection
from core.llm.embeddings import embed_text


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = _parse_args(argv)
    if args.rebuild:
        for collection in args.collections:
            chroma.rebuild_collection(collection, workspace_id=args.workspace_id)
    embedding = embed_text(args.query)
    results = {
        "query": args.query,
        "embedding_dimensions": len(embedding),
        "workspace_id": args.workspace_id,
        "vector_store": chroma.vector_store_status(args.workspace_id),
        "results": {
            collection: _search_collection(collection, embedding, args.limit, args.workspace_id)
            for collection in args.collections
        },
    }
    print(json.dumps(results, indent=2, sort_keys=True, default=str))
    return 0


def _search_collection(
    collection: str,
    embedding: list[float],
    limit: int,
    workspace_id: str,
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for pointer in chroma.query_embeddings(
        collection, embedding, top_k=limit, workspace_id=workspace_id
    ):
        table = str(pointer["sqlite_table"])
        sqlite_id = str(pointer["sqlite_id"])
        record = _fetch_record(table, sqlite_id, workspace_id)
        output.append(
            {
                "sqlite_table": table,
                "sqlite_id": sqlite_id,
                "record_found": record is not None,
                "distance": pointer.get("distance"),
                "metadata": pointer.get("metadata", {}),
                "content": _record_content(table, record) if record else None,
            }
        )
    return output


def _fetch_record(table: str, sqlite_id: str, workspace_id: str) -> dict[str, object] | None:
    if table not in chroma.SUPPORTED_COLLECTIONS:
        return None
    with repository_connection() as connection:
        row = connection.execute(
            f"SELECT * FROM {table} WHERE id = ? AND workspace_id = ?",  # nosec B608
            (sqlite_id, workspace_id),
        ).fetchone()
    return None if row is None else dict(row)


def _record_content(table: str, record: dict[str, object]) -> str:
    if table in {"observations", "reflections"}:
        return str(record["content"])
    if table == "community_summaries":
        return f"{record['title']}\n\n{record['summary']}"
    return ""


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Text to embed and search for.")
    parser.add_argument(
        "--workspace-id",
        required=True,
        help="Workspace whose vectors and canonical SQLite records may be inspected.",
    )
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument(
        "--collections",
        nargs="+",
        default=["observations", "reflections"],
        choices=sorted(chroma.SUPPORTED_COLLECTIONS),
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Rebuild selected collections first.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
