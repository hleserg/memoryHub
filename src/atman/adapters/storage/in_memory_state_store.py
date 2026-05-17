"""In-memory implementation of StateStore for fast unit tests.

This implementation stores all state in memory dictionaries.
Use for unit tests where file I/O is not needed.
For integration tests, use FileStateStore.
"""

from datetime import UTC, datetime
from uuid import UUID

from atman.core.clock_impl import ensure_utc
from atman.core.models import (
    Eigenstate,
    ExperienceRecord,
    Identity,
    IdentitySnapshot,
    KeyMoment,
    NarrativeDocument,
    ReframingNote,
)
from atman.core.models.session import Session
from atman.core.ports.state_store import (
    DateRangeQuery,
    DepthQuery,
    ExperienceQuery,
    FactRefsContainsQuery,
    SessionExperienceQuery,
    StateStore,
    ValuesTouchedQuery,
)


class InMemoryStateStore(StateStore):
    """In-memory implementation of StateStore for unit tests."""

    def __init__(self) -> None:
        """Initialize empty in-memory storage."""
        self._experiences: dict[UUID, ExperienceRecord] = {}
        self._key_moments: dict[UUID, KeyMoment] = {}  # moment_id -> KeyMoment
        self._session_moments: dict[UUID, list[UUID]] = {}  # session_id -> [moment_ids]
        self._sessions: dict[UUID, Session] = {}
        self._identities: dict[UUID, Identity] = {}
        self._identity_snapshots: dict[UUID, IdentitySnapshot] = {}
        self._narratives: dict[UUID, NarrativeDocument] = {}
        self._archived_narratives: dict[UUID, list[tuple[NarrativeDocument, str, datetime]]] = {}
        self._eigenstates: list[Eigenstate] = []

    def create_experience(self, record: ExperienceRecord) -> ExperienceRecord:
        """Store experience in memory."""
        if record.experience.id in self._experiences:
            raise ValueError(f"Experience {record.experience.id} already exists")
        self._experiences[record.experience.id] = record.model_copy(deep=True)
        return record

    def get_experience(self, experience_id: UUID) -> ExperienceRecord | None:
        """Retrieve experience by ID."""
        record = self._experiences.get(experience_id)
        return record.model_copy(deep=True) if record else None

    def add_reframing_note(
        self, experience_id: UUID, note: ReframingNote
    ) -> ExperienceRecord | None:
        """Add reframing note to experience (legacy — experience is read-only view in v2).

        Dedup-by-trigger: if a note with the same non-empty ``triggered_by``
        already exists, the new note is NOT appended and the existing record
        is returned unchanged. Mirrors :class:`FileStateStore` and
        :class:`InMemoryExperienceStore` behaviour.
        """
        record = self._experiences.get(experience_id)
        if record is None:
            return None
        if note.triggered_by and any(
            n.triggered_by == note.triggered_by for n in record.experience.reframing_notes
        ):
            return record
        updated = record.model_copy(deep=True)
        updated.experience.reframing_notes.append(note)
        self._experiences[experience_id] = updated
        return updated

    def mark_accessed(self, experience_id: UUID) -> ExperienceRecord | None:
        """Mark experience as accessed (legacy)."""
        record = self._experiences.get(experience_id)
        if record is None:
            return None
        updated = record.model_copy(deep=True)
        updated.experience.last_accessed_at = datetime.now(UTC)
        updated.experience.access_count += 1
        self._experiences[experience_id] = updated
        return updated

    def search_experiences(
        self, query: ExperienceQuery | None = None, limit: int = 10
    ) -> list[ExperienceRecord]:
        """Search experiences by query."""
        results = list(self._experiences.values())

        if query is None:
            # Return all experiences, newest first
            results.sort(key=lambda r: r.experience.timestamp, reverse=True)
            return [r.model_copy(deep=True) for r in results[:limit]]

        if isinstance(query, SessionExperienceQuery):
            results = [
                r
                for r in results
                if hasattr(r.experience, "session_id")
                and r.experience.session_id == query.session_id
            ]
        elif isinstance(query, ValuesTouchedQuery):
            results = [
                r
                for r in results
                if any(
                    value in moment.values_touched
                    for moment_id in r.experience.key_moment_ids
                    if (moment := self._key_moments.get(moment_id)) is not None
                    for value in query.values
                )
            ]
        elif isinstance(query, DepthQuery):
            results = [
                r
                for r in results
                if any(
                    moment.how_i_felt.depth.value == query.depth
                    for moment_id in r.experience.key_moment_ids
                    if (moment := self._key_moments.get(moment_id)) is not None
                )
            ]
        elif isinstance(query, DateRangeQuery):
            results = [
                r for r in results if query.start_date <= r.experience.timestamp <= query.end_date
            ]
        elif isinstance(query, FactRefsContainsQuery):
            results = [
                r
                for r in results
                if any(
                    query.fact_id in moment.fact_refs
                    for moment_id in r.experience.key_moment_ids
                    if (moment := self._key_moments.get(moment_id)) is not None
                )
            ]

        results.sort(key=lambda r: r.experience.timestamp, reverse=True)
        return [r.model_copy(deep=True) for r in results[:limit]]

    def list_recent_experiences(self, limit: int = 10) -> list[ExperienceRecord]:
        """List recent experiences."""
        results = list(self._experiences.values())
        results.sort(key=lambda r: r.experience.timestamp, reverse=True)
        return [r.model_copy(deep=True) for r in results[:limit]]

    def store_key_moments(self, session_id: UUID, moments: list[KeyMoment]) -> None:
        """Store key moments for a session."""
        moment_ids = []
        for moment in moments:
            self._key_moments[moment.id] = moment.model_copy(deep=True)
            moment_ids.append(moment.id)
        self._session_moments[session_id] = moment_ids

    def get_key_moment(self, moment_id: UUID) -> KeyMoment | None:
        """Retrieve a key moment by its ID."""
        moment = self._key_moments.get(moment_id)
        return moment.model_copy(deep=True) if moment else None

    def get_key_moments_for_session(self, session_id: UUID) -> list[KeyMoment]:
        """Retrieve all key moments for a session."""
        moment_ids = self._session_moments.get(session_id, [])
        moments = []
        for moment_id in moment_ids:
            moment = self._key_moments.get(moment_id)
            if moment:
                moments.append(moment.model_copy(deep=True))
        return moments

    def load_identity(self, agent_id: UUID) -> Identity | None:
        """Load identity by agent ID."""
        identity = self._identities.get(agent_id)
        return identity.model_copy(deep=True) if identity else None

    def save_identity(self, identity: Identity, expected_version: str | None = None) -> Identity:
        """Save identity."""
        if expected_version is not None:
            existing = self._identities.get(identity.id)
            if existing and existing.schema_version != expected_version:
                raise ValueError(
                    f"Identity version mismatch: expected {expected_version}, "
                    f"got {existing.schema_version}"
                )
        self._identities[identity.id] = identity.model_copy(deep=True)
        return identity

    def create_identity_snapshot(self, snapshot: IdentitySnapshot) -> IdentitySnapshot:
        """Store identity snapshot."""
        if snapshot.id in self._identity_snapshots:
            raise ValueError(f"IdentitySnapshot {snapshot.id} already exists")
        self._identity_snapshots[snapshot.id] = snapshot.model_copy(deep=True)
        return snapshot

    def list_identity_snapshots(self, identity_id: UUID, limit: int = 10) -> list[IdentitySnapshot]:
        """List identity snapshots."""
        snapshots = [s for s in self._identity_snapshots.values() if s.identity_id == identity_id]
        snapshots.sort(key=lambda s: s.timestamp, reverse=True)
        return [s.model_copy(deep=True) for s in snapshots[:limit]]

    def load_narrative(self, identity_id: UUID) -> NarrativeDocument | None:
        """Load narrative by identity ID."""
        narrative = self._narratives.get(identity_id)
        return narrative.model_copy(deep=True) if narrative else None

    def save_narrative(
        self,
        narrative: NarrativeDocument,
        expected_version: str | None = None,
        expected_updated_at: datetime | None = None,
    ) -> NarrativeDocument:
        """Save narrative."""
        if expected_version is not None:
            existing = self._narratives.get(narrative.identity_id)
            if existing and existing.schema_version != expected_version:
                raise ValueError(
                    f"Narrative version mismatch: expected {expected_version}, "
                    f"got {existing.schema_version}"
                )
        if expected_updated_at is not None:
            existing = self._narratives.get(narrative.identity_id)
            if existing and existing.updated_at != expected_updated_at:
                raise ValueError(
                    f"Narrative updated_at mismatch: expected {expected_updated_at}, "
                    f"got {existing.updated_at} (concurrent update detected)"
                )
        self._narratives[narrative.identity_id] = narrative.model_copy(deep=True)
        return narrative

    def archive_narrative(self, narrative_id: UUID, reason: str) -> None:
        """Archive narrative."""
        # Find narrative by its document ID across all stored narratives
        narrative = None
        for stored_narrative in self._narratives.values():
            if stored_narrative.id == narrative_id:
                narrative = stored_narrative
                break

        if narrative is None:
            return

        # Store archived narratives by identity_id for filtering
        identity_id = narrative.identity_id
        if identity_id not in self._archived_narratives:
            self._archived_narratives[identity_id] = []
        from datetime import UTC

        self._archived_narratives[identity_id].append(
            (narrative.model_copy(deep=True), reason, datetime.now(UTC))
        )

    def list_archived_narratives(
        self, identity_id: UUID, limit: int = 10
    ) -> list[tuple[NarrativeDocument, str, datetime]]:
        """List archived narratives."""
        archived = self._archived_narratives.get(identity_id, [])
        archived.sort(key=lambda x: x[2], reverse=True)
        return [(n.model_copy(deep=True), r, a) for n, r, a in archived[:limit]]

    def save_eigenstate(self, eigenstate: Eigenstate) -> Eigenstate:
        """Save eigenstate (idempotent - upserts by eigenstate.id)."""
        # Remove existing eigenstate with same id for idempotent retry
        self._eigenstates = [e for e in self._eigenstates if e.id != eigenstate.id]
        self._eigenstates.append(eigenstate.model_copy(deep=True))
        return eigenstate

    def load_latest_eigenstate(
        self,
        session_id: UUID | None = None,
        identity_id: UUID | None = None,
    ) -> Eigenstate | None:
        """Load latest eigenstate."""
        candidates = self._eigenstates

        if session_id is not None:
            candidates = [e for e in candidates if e.session_id == session_id]

        if identity_id is not None:
            candidates = [e for e in candidates if e.identity_id == identity_id]

        if not candidates:
            return None

        # Return most recent by timestamp
        latest = max(candidates, key=lambda e: e.timestamp)
        return latest.model_copy(deep=True)

    def create_key_moment(self, key_moment: KeyMoment) -> KeyMoment:
        """Store key moment in memory. Raises ValueError if duplicate id."""
        if key_moment.id in self._key_moments:
            raise ValueError(f"KeyMoment {key_moment.id} already exists")
        self._key_moments[key_moment.id] = key_moment.model_copy(deep=True)
        if key_moment.session_id is not None:
            ids = self._session_moments.setdefault(key_moment.session_id, [])
            if key_moment.id not in ids:
                ids.append(key_moment.id)
        return key_moment

    def store_key_moment(self, moment: KeyMoment) -> KeyMoment:
        """Store key moment idempotently (v2 API — upsert by id)."""
        self._key_moments[moment.id] = moment.model_copy(deep=True)
        if moment.session_id is not None:
            ids = self._session_moments.setdefault(moment.session_id, [])
            if moment.id not in ids:
                ids.append(moment.id)
        return moment

    def list_key_moments(self, session_id: UUID | None = None) -> list[KeyMoment]:
        """List key moments, optionally filtered by session_id."""
        if session_id is not None:
            ids = self._session_moments.get(session_id, [])
            moments = [self._key_moments[i] for i in ids if i in self._key_moments]
        else:
            moments = list(self._key_moments.values())
        return [m.model_copy(deep=True) for m in moments]

    def mark_moment_accessed(self, moment_id: UUID) -> None:
        """Update last_accessed_at and increment access_count."""
        moment = self._key_moments.get(moment_id)
        if moment:
            moment.mark_accessed()

    def update_moment_structured_markers(
        self, moment_id: UUID, markers: dict, version: str
    ) -> None:
        """Update structured_markers on a stored key moment."""
        moment = self._key_moments.get(moment_id)
        if moment:
            moment.structured_markers = markers
            moment.structured_markers_version = version

    # Session operations (v2)

    def create_session(self, session: Session) -> Session:
        """Persist a new session record."""
        self._sessions[session.id] = session.model_copy(deep=True)
        return session

    def get_session(self, session_id: UUID) -> Session | None:
        """Retrieve session by ID."""
        s = self._sessions.get(session_id)
        return s.model_copy(deep=True) if s else None

    def update_session(self, session: Session) -> Session:
        """Update session metadata."""
        self._sessions[session.id] = session.model_copy(deep=True)
        return session

    def list_recent_sessions(self, agent_id: UUID, *, limit: int = 10) -> list[Session]:
        """List most recent sessions for an agent, newest first."""
        sessions = [s for s in self._sessions.values() if s.agent_id == agent_id]
        sessions.sort(key=lambda s: ensure_utc(s.started_at), reverse=True)
        return [s.model_copy(deep=True) for s in sessions[:limit]]
