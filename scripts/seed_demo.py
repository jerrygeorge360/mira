"""Seed scripted demo data into MIRA.

Populates the database with a scripted conversation so the demo mode (and the
UI/eval work that depends on it) has realistic memory to render without waiting
for real conversations to accumulate.

Run with: python scripts/seed_demo.py

ISSUE-020: Demo mode seed (owned by Sarah; stub provided to unblock).
"""

from __future__ import annotations


def seed() -> None:
    """Load the scripted demo conversation into the configured database."""
    raise NotImplementedError


def main() -> None:
    """Run the demo seeder as a standalone script."""
    raise NotImplementedError


if __name__ == "__main__":
    main()
