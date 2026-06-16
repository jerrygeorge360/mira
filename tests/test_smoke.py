"""Smoke tests for the MIRA bootstrap.

Guards the scaffold itself: the package imports cleanly and every stubbed
entry point is wired up but not yet implemented. These tests are replaced by
real coverage as each issue is implemented.

ISSUE-001: Bootstrap smoke tests.
"""

from __future__ import annotations

import pytest

import core


def test_package_version() -> None:
    """The core package exposes a version string."""
    assert isinstance(core.__version__, str)
    assert core.__version__


def test_agent_is_not_yet_implemented() -> None:
    """The agent entry point is stubbed pending ISSUE-001 implementation."""
    from core.agent import Agent

    with pytest.raises(NotImplementedError):
        Agent(session_id="smoke")
