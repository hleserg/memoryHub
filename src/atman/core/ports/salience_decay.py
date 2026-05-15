"""Port: SalienceDecayService — decay salience of stale key moments."""

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID


class SalienceDecayService(ABC):
    """Abstract port for applying exponential salience decay to experiences."""

    @abstractmethod
    def decay_pass(
        self,
        agent_id: UUID,
        *,
        cutoff: datetime,
        decay_lambda_surface: float = 0.05,
        decay_lambda_meaningful: float = 0.02,
        decay_lambda_profound: float = 0.005,
        min_salience: float = 0.01,
    ) -> int:
        """
        Decay salience for key moments not accessed since cutoff.

        Returns count of moments updated.

        Formula: salience *= exp(-lambda * days_since_access)
        Lambda depends on depth (surface > meaningful > profound).
        """

    @abstractmethod
    def mark_accessed(self, moment_id: UUID) -> None:
        """Update last_accessed_at=now() and increment access_count."""

    @abstractmethod
    def calculate_lambda(self, depth: str, importance: float) -> float:
        """Calculate decay lambda for given depth and importance level."""
