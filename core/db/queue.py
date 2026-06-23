"""Define the persistence-backed queue contract between fast and slow paths.

Ownership: Kelechi.
Related issue: ISSUE-505.
Architecture area: fast path.
"""


def enqueue_observation(observation_id: str) -> None:
    """Queue a persisted observation for future slow-path processing."""
    raise NotImplementedError


def claim_observation() -> str | None:
    """Claim the next observation identifier for future enrichment."""
    raise NotImplementedError
