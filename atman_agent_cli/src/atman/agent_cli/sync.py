"""
RAG index sync helpers — staleness messaging for callers (CLI / TUIs).

Call :func:`rag_staleness_chat_message` at startup alongside your Rich layer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .rag import RAGIndex


def rag_staleness_chat_message(rag: RAGIndex) -> str | None:
    """
    Rich-formatted line when the persisted index is older than ``rag_stale_hours``.
    Returns None when the index timestamp is acceptable.
    """
    if rag.check_staleness():
        return "[yellow]\u26a0[/yellow] RAG index may be outdated — rebuild with [green]/index[/green]."
    return None
