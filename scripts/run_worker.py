"""Background slow-path memory worker entrypoint.

Ownership: Jerry.
Related issue: ISSUE-124.
Architecture area: worker.

Drains MIRA's slow-path queue through the ISSUE-121 orchestrator so queued
observations become durable cross-session memory continuously, without manual
calls. The chat path stays fast: it only enqueues; this worker consolidates.

    python -m scripts.run_worker --batch-size 20 --poll-interval 2
"""

from __future__ import annotations

import argparse
import logging
import sys


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, configure the runtime, and run the worker."""
    args = _parse_args(argv)

    from core.observability import configure_logging, log_event

    configure_logging(level=getattr(logging, args.log_level.upper(), logging.INFO))

    if args.db:
        from core.db.repositories import configure_database

        configure_database(args.db)

    from core.memory.slow_path import get_slow_path_queue_status, run_worker

    if args.dry_run:
        status = get_slow_path_queue_status()
        log_event(
            "worker_dry_run",
            "queue inspected without processing",
            worker_id=args.worker_id,
            queue_pending=status["pending"],
            queue_processing=status["processing"],
            queue_done=status["done"],
            queue_failed=status["failed"],
            queue_dead_letter=status["dead_letter"],
        )
        print(status)
        return 0

    summary = run_worker(
        batch_size=args.batch_size,
        poll_interval_s=args.poll_interval,
        once=args.once,
        max_iterations=args.max_iterations,
        worker_id=args.worker_id,
    )
    print(
        f"worker done: processed={summary['processed']} "
        f"failed={summary['failed']} iterations={summary['iterations']}"
    )
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run_worker",
        description="Run the slow-path background memory worker.",
    )
    parser.add_argument("--batch-size", type=int, default=20, help="Observations per batch.")
    parser.add_argument(
        "--poll-interval", type=float, default=2.0, help="Seconds to sleep when idle."
    )
    parser.add_argument("--once", action="store_true", help="Process one batch and exit.")
    parser.add_argument(
        "--max-iterations", type=int, default=None, help="Stop after N poll iterations."
    )
    parser.add_argument("--db", default=None, help="Optional SQLite database path.")
    parser.add_argument("--worker-id", default="slow-path-worker", help="Worker id for logs.")
    parser.add_argument("--log-level", default="INFO", help="Logging verbosity.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Inspect queue health without processing."
    )
    return parser.parse_args(argv)


if __name__ == "__main__":  # pragma: no cover - module entry point
    sys.exit(main())
