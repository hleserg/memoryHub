"""In-memory EntityStanceStore adapter."""

import threading
from datetime import UTC, datetime
from uuid import UUID, uuid4

from atman.core.models.entity import EntityStance
from atman.core.ports.entity_stance import EntityStanceStore


class InMemoryEntityStanceStore(EntityStanceStore):
    """Thread-safe in-memory EntityStanceStore for tests and lightweight use."""

    def __init__(self) -> None:
        self._stances: dict[UUID, EntityStance] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_current_stance(self, agent_id: UUID, entity_id: UUID) -> EntityStance | None:
        """Return the active (not superseded) stance, or None."""
        with self._lock:
            for stance in self._stances.values():
                if (
                    stance.agent_id == agent_id
                    and stance.entity_id == entity_id
                    and stance.superseded_at is None
                ):
                    return stance
        return None

    def get_stance_history(self, agent_id: UUID, entity_id: UUID) -> list[EntityStance]:
        """Return all stances for entity, newest first."""
        with self._lock:
            matches = [
                s
                for s in self._stances.values()
                if s.agent_id == agent_id and s.entity_id == entity_id
            ]
        return sorted(matches, key=lambda s: s.formed_at, reverse=True)

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def write_stance(
        self,
        agent_id: UUID,
        entity_id: UUID,
        stance_text: str,
        *,
        valence: float | None = None,
        intensity: float | None = None,
        formed_in_reflection_id: UUID | None = None,
        based_on_moment_ids: list[UUID] | None = None,
        confidence: float | None = None,
        is_provisional: bool = True,
    ) -> EntityStance:
        """Create new stance, superseding any existing active stance."""
        new_id = uuid4()

        with self._lock:
            # Supersede the current active stance if one exists
            current = None
            for stance in self._stances.values():
                if (
                    stance.agent_id == agent_id
                    and stance.entity_id == entity_id
                    and stance.superseded_at is None
                ):
                    current = stance
                    break

            if current is not None:
                current.superseded_at = datetime.now(UTC)
                current.superseded_by = new_id

            new_stance = EntityStance(
                id=new_id,
                agent_id=agent_id,
                entity_id=entity_id,
                stance_text=stance_text,
                valence=valence,
                intensity=intensity,
                formed_in_reflection_id=formed_in_reflection_id,
                based_on_moment_ids=based_on_moment_ids or [],
                confidence=confidence,
                is_provisional=is_provisional,
            )
            self._stances[new_id] = new_stance

        return new_stance

    def supersede_stance(self, stance_id: UUID, *, superseded_by_id: UUID) -> None:
        """Mark a stance as superseded."""
        with self._lock:
            stance = self._stances.get(stance_id)
            if stance is None:
                return
            stance.superseded_at = datetime.now(UTC)
            stance.superseded_by = superseded_by_id

    def list_active_stances(
        self,
        agent_id: UUID,
        *,
        formed_after: datetime | None = None,
        limit: int = 50,
    ) -> list[EntityStance]:
        """List all active stances for the agent, sorted newest first."""
        with self._lock:
            matches = [
                s
                for s in self._stances.values()
                if (
                    s.agent_id == agent_id
                    and s.superseded_at is None
                    and (formed_after is None or s.formed_at > formed_after)
                )
            ]
        matches.sort(key=lambda s: s.formed_at, reverse=True)
        return matches[:limit]
