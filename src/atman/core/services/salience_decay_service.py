"""SalienceDecayService — exponential salience decay for key moments."""

import math
from datetime import UTC, datetime
from uuid import UUID

from atman.core.models.experience import EmotionalDepth
from atman.core.ports.salience_decay import SalienceDecayService
from atman.core.ports.state_store import StateStore


class InMemorySalienceDecayService(SalienceDecayService):
    """
    Framework-agnostic SalienceDecayService backed by StateStore.

    Operates on KeyMoment records (v2 architecture). Key moments carry
    `salience`, `salience_at`, `last_accessed_at`, `access_count`, and
    `how_i_felt.depth` for choosing the decay rate. Updated moments are
    persisted via `store_key_moment` (idempotent upsert), so changes
    survive across `list_key_moments` calls that return deep copies.
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
        Decay salience for key moments not accessed since cutoff.

        Iterates all KeyMoment objects from the store. For each moment whose
        `last_accessed_at` is before the cutoff, applies:

            new_salience = max(min_salience, salience * exp(-lambda * days))

        The lambda is chosen based on the moment's emotional depth:
          - profound   → decay_lambda_profound
          - meaningful → decay_lambda_meaningful
          - surface    → decay_lambda_surface

        Updated moments are persisted via `store_key_moment` (idempotent
        upsert). Returns the count of moments whose salience was updated.

        Note on `agent_id` scoping:
            The StateStore is agent-scoped at the boundary — per-agent schema
            in Postgres, per-process instance in-memory — so additional
            agent_id filtering is not required here. agent_id is accepted to
            satisfy the port contract and to allow future multi-tenant stores
            to filter.
        """
        del agent_id  # scoping at StateStore boundary; see docstring
        now = datetime.now(UTC)
        moments = self._store.list_key_moments()

        cutoff_aware = cutoff if cutoff.tzinfo is not None else cutoff.replace(tzinfo=UTC)
        now_aware = now if now.tzinfo is not None else now.replace(tzinfo=UTC)

        updated = 0
        for moment in moments:
            last_accessed = moment.last_accessed_at
            if last_accessed.tzinfo is None:
                last_accessed = last_accessed.replace(tzinfo=UTC)

            if last_accessed >= cutoff_aware:
                continue

            depth = moment.how_i_felt.depth
            if depth == EmotionalDepth.PROFOUND:
                base_lambda = decay_lambda_profound
            elif depth == EmotionalDepth.MEANINGFUL:
                base_lambda = decay_lambda_meaningful
            else:
                base_lambda = decay_lambda_surface

            # Mirror the high-importance adjustment from calculate_lambda() and
            # KeyMoment.calculate_current_salience() so all three decay paths
            # (port-level, model-level, service-level) agree on lambda for the
            # same moment. Without this the background worker decays a
            # high-importance moment faster than the model preview suggests.
            importance_adjustment = 0.7 if moment.importance > 0.8 else 1.0
            lam = base_lambda * importance_adjustment

            days = (now_aware - last_accessed).total_seconds() / 86400.0
            new_salience = max(min_salience, moment.salience * math.exp(-lam * days))

            if new_salience != moment.salience:
                moment.salience = new_salience
                moment.salience_at = now_aware
                # Persist the updated moment via idempotent upsert.
                self._store.store_key_moment(moment)
                updated += 1

        return updated

    def mark_accessed(self, moment_id: UUID) -> None:
        """Mark a key moment as accessed (updates last_accessed_at, access_count)."""
        self._store.mark_moment_accessed(moment_id)
