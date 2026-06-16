"""Chat front-end application for MIRA.

Entry point for the interactive UI: renders the conversation, forwards user
turns to the agent, and streams responses back to the browser.

ISSUE-016: UI app.
"""

from __future__ import annotations


def create_app() -> object:
    """Construct and configure the MIRA UI application instance.

    Returns:
        The configured application object ready to be served.
    """
    raise NotImplementedError


def main() -> None:
    """Run the UI application as a standalone process."""
    raise NotImplementedError


if __name__ == "__main__":
    main()
