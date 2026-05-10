"""
MemoryMiddlewarePort - integration point for live agent.

Protocol for memory middleware that sits between the live agent
and memory stores, managing passive memory surfacing and tracking.
This is the integration point for future live agent (MODEL-02).
"""

from abc import abstractmethod
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from atman.core.models import FactRecord, SessionExperience


@dataclass
class MemoryContext:
    """Memory context provided to the agent."""

    relevant_facts: list[FactRecord]
    relevant_experiences: list[SessionExperience]
    emotional_echo: str  # Summary of recent emotional context
    conflicts: list[str]  # Any detected conflicts (as descriptions)


class MemoryMiddlewarePort(Protocol):
    """
    Middleware between live agent and memory stores.

    This protocol defines the interface for memory middleware that:
    1. Surfaces relevant context based on current situation
    2. Tracks what memory was actually used
    3. Manages working memory during sessions

    Note: This is just the protocol. Concrete implementation
    requires live agent from MODEL-02.
    """

    @abstractmethod
    def prepare_context(
        self,
        session_id: UUID,
        situation: str,
    ) -> MemoryContext:
        """
        Prepare memory context for a situation.

        Args:
            session_id: Current session ID
            situation: Description of current situation/context

        Returns:
            MemoryContext: Relevant facts, experiences, and emotional echo
        """
        pass

    @abstractmethod
    def note_fact_used(
        self,
        session_id: UUID,
        fact_id: UUID,
        usage_type: str,
        context: str,
    ) -> None:
        """
        Note that a fact was used.

        Args:
            session_id: Current session
            fact_id: The fact that was used
            usage_type: How it was used (e.g., "cited", "influenced")
            context: Brief context of usage
        """
        pass

    @abstractmethod
    def end_session(self, session_id: UUID) -> None:
        """
        End session and cleanup working memory.

        Args:
            session_id: Session to end
        """
        pass
