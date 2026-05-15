"""SalienceDecayService — exponential salience decay for key moments."""

import math
from datetime import UTC, datetime
from uuid import UUID

from atman.core.ports.salience_decay import SalienceDecayService
from atman.core.ports.state_store import StateStore


class InMemorySalienceDecayService(SalienceDecayService):
    """
    Framework-agnostic SalienceDecayService backed by StateStore.

    Operates on ExperienceRecord objects, which carry salience,
    last_accessed_at, and depth metadata (has_profound_moment,
    avg_emotional_intensity). Records are retrieved via the StateStore
    and updated in-place through mark_accessed / direct field mutation.
    """

    def __init__(self, state_store: StateStore) -> None:
        self._store = state_store

    def calculate_lambda(self, depth: str, importance: float) -> float:
        """
        Calculate decay lambda for given depth and importance level.

        Base lambdas by depth:
          - surface:    0.05  (fastest decay)
          - meaningful: 0.02
          - profound:   0.005 (slowest decay)

        High-importance memories (importance > 0.8) decay 30% slower.
        """
        _base = {
            "surface": 0.05,
            "meaningful": 0.02,
            "profound": 0.005,
        }
        base_lambda = _base.get(depth, 0.05)
        adjustment = 0.7 if importance > 0.8 else 1.0
        return base_lambda * adjustment

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
        Decay salience for experiences not accessed since cutoff.

        Iterates all ExperienceRecord objects from the store. For each
        record whose last_accessed_at is before the cutoff, applies:

            new_salience = max(min_salience, salience * exp(-lambda * days))

        The lambda is chosen based on depth metadata:
          - has_profound_moment=True  → decay_lambda_profound
          - avg_emotional_intensity >= 0.6 → decay_lambda_meaningful
          - otherwise                 → decay_lambda_surface

        Returns the count of records whose salience was actually updated.
        """
        now = datetime.now(UTC)
        # Retrieve all experiences; large limit covers in-memory stores.
        records = self._store.list_recent_experiences(limit=10_000)

        updated = 0
        for record in records:
            exp = record.experience
            last_accessed = exp.last_accessed_at

            # Ensure both datetimes are comparable (add UTC if naive)
            if last_accessed.tzinfo is None:
                last_accessed = last_accessed.replace(tzinfo=UTC)
            cutoff_aware = cutoff if cutoff.tzinfo is not None else cutoff.replace(tzinfo=UTC)

            if last_accessed >= cutoff_aware:
                continue

            # Choose decay lambda based on depth metadata
            if exp.has_profound_moment:
                lam = decay_lambda_profound
            elif exp.avg_emotional_intensity >= 0.6:
                lam = decay_lambda_meaningful
            else:
                lam = decay_lambda_surface

            now_aware = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
            days = (now_aware - last_accessed).total_seconds() / 86400.0
            new_salience = max(min_salience, exp.salience * math.exp(-lam * days))

            if new_salience != exp.salience:
                exp.salience = new_salience
                updated += 1

        return updated

    def mark_accessed(self, moment_id: UUID) -> None:
        """
        Update last_accessed_at and increment access_count for an experience.

        Delegates to StateStore.mark_accessed, which treats the moment_id
        as an ExperienceRecord identifier.
        """
        self._store.mark_accessed(moment_id)
