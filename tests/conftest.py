"""Shared pytest fixtures for the MIRA test suite.

Fixtures land here as the modules they support gain real implementations.
``pytest-asyncio`` is configured in auto mode (see pyproject.toml) so async
tests for the slow-path worker and Slack bot need no per-test markers.

ISSUE-001: Test fixtures bootstrap.
"""

from __future__ import annotations
