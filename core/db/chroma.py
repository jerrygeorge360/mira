"""ChromaDB vector-index adapter contract with no source-of-truth authority.

Ownership: Kelechi.
Related issue: ISSUE-503.
Architecture area: retrieval.
"""


def index_memory(memory_id: str, text: str, metadata: dict[str, object]) -> None:
    """Index a durable memory representation in the future vector index."""
    raise NotImplementedError


def remove_from_index(memory_id: str) -> None:
    """Remove a durable memory representation from the vector index."""
    raise NotImplementedError
