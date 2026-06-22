"""Asynchronous durable enrichment pipeline contract for cross-session memory.

Ownership: Jerry.
Related issue: ISSUE-103.
Architecture area: slow path.
"""


async def enrich_observation(observation_id: str) -> None:
    """Synthesize durable memory artifacts from one queued observation."""
    raise NotImplementedError


async def run_slow_path(batch_size: int = 20) -> None:
    """Process a future batch of queued observations asynchronously."""
    raise NotImplementedError
