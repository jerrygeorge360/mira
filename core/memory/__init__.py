"""Dual-stream memory subsystem for MIRA.

Implements the fast path (synchronous observation of incoming turns) and the
slow path (asynchronous consolidation: reflection, foresight, graph and
community maintenance) that together form MIRA's cognitive memory.

ISSUE-004: Memory subsystem bootstrap.
"""
