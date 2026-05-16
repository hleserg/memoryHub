"""
End-to-end system test exercising SYSTEM_MAP §3 scenarios A–G.

Bootstrap → record experiences → micro / daily / deep reflection →
narrative render. Uses the real ``FileStateStore`` for identity / narrative /
experience persistence and minimal in-process reflection repositories.

This test is a SYSTEM_MAP §5.3 regression freeze: it verifies the orchestration
of multiple services keeps working as the codebase evolves.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

import pytest

from atman.adapters.reflection.mock_reflection_model import MockReflectionModel
from atman.adapters.reflection.state_store_session_repository import (
    StateStoreSessionRepository,
)
from atman.adapters.storage import FileStateStore
from atman.adapters.storage.in_memory_reflection_store import (
    InMemoryHealthAssessmentStore,
    InMemoryPatternStore,
    InMemoryReflectionEventStore,
)
from atman.core.models import (
    EmotionalDepth,
    FeltSense,
    KeyMoment,
    Session,
    SessionExperience,
)
from atman.core.models.experience import (
    ReframingNote,
    ReframingNoteAppendResult,
)
from atman.core.models.identity import Identity, IdentitySnapshot
from atman.core.models.narrative import (
    NarrativeDocument,
)
from atman.core.models.reflection import ReflectionLevel
from atman.core.narrative_write_audit import NoOpNarrativeWriteAudit
from atman.core.ports.state_store import (
    DateRangeQuery,
    SessionExperienceQuery,
)
from atman.core.services.experience_service import ExperienceService
from atman.core.services.identity_service import IdentityService
from atman.core.services.narrative_revision import NarrativeRevisionService
from atman.core.services.narrative_service import NarrativeService
from atman.core.services.reflection_service import (
    DailyReflectionService,
    DeepReflectionService,
    MicroReflectionService,
)


class _StateStoreExperienceRepo:
    """Adapt ``FileStateStore`` to the ``ExperienceRepository`` protocol used by reflection."""

    def __init__(self, store: FileStateStore) -> None:
        self.store = store

    def get(self, experience_id: UUID) -> SessionExperience | None:
        rec = self.store.get_experience(experience_id)
        return rec.experience if rec else None

    def get_all(self) -> list[SessionExperience]:
        return [r.experience for r in self.store.list_recent_experiences(limit=10_000)]

    def get_by_session(self, session_id: UUID) -> list[SessionExperience]:
        records = self.store.search_experiences(
            query=SessionExperienceQuery(session_id=session_id), limit=10_000
        )
        return [r.experience for r in records]

    def get_recent(self, limit: int = 10) -> list[SessionExperience]:
        return [r.experience for r in self.store.list_recent_experiences(limit=limit)]

    def get_in_range(self, start: datetime, end: datetime) -> list[SessionExperience]:
        records = self.store.search_experiences(
            query=DateRangeQuery(start_date=start, end_date=end), limit=10_000
        )
        return [r.experience for r in records]

    def update(self, experience: SessionExperience) -> None:
        # No-op for this adapter: experiences are immutable in StateStore.
        return None

    def add_reframing_note(
        self, experience_id: UUID, note: ReframingNote
    ) -> ReframingNoteAppendResult:
        existing = self.store.get_experience(experience_id)
        if existing is None:
            return ReframingNoteAppendResult.EXPERIENCE_NOT_FOUND
        if note.triggered_by and any(
            n.triggered_by == note.triggered_by for n in existing.experience.reframing_notes
        ):
            return ReframingNoteAppendResult.DUPLICATE_TRIGGERED_BY
        result = self.store.add_reframing_note(experience_id, note)
        if result is None:
            return ReframingNoteAppendResult.EXPERIENCE_NOT_FOUND
        return ReframingNoteAppendResult.STORED


class _InMemoryIdentityRepo:
    """``IdentityRepository`` adapter writing through to a ``FileStateStore``."""

    def __init__(self, store: FileStateStore, identity: Identity) -> None:
        self.store = store
        self.identity = identity
        self._snapshots: dict[UUID, IdentitySnapshot] = {}

    def get_current(self) -> Identity | None:
        return self.identity

    def get_snapshot(self, snapshot_id: UUID) -> IdentitySnapshot | None:
        return self._snapshots.get(snapshot_id)

    def get_history(self) -> list[IdentitySnapshot]:
        return list(self._snapshots.values())

    def update(self, identity: Identity) -> None:
        self.identity = identity
        self.store.save_identity(identity)

    def create_snapshot(
        self,
        identity: Identity,
        description: str,
        change_summary: str,
        *,
        snapshot_id: UUID | None = None,
    ) -> IdentitySnapshot:
        sid = snapshot_id or uuid4()
        snap = IdentitySnapshot(
            id=sid,
            identity_id=identity.id,
            identity_snapshot=identity.model_copy(deep=True),
            description=description,
            change_summary=change_summary,
        )
        self._snapshots[sid] = snap
        self.store.create_identity_snapshot(snap)
        return snap


class _NarrativeRepoOverFileStateStore:
    """``NarrativeRepository`` wrapper preserving optimistic concurrency on ``updated_at``."""

    def __init__(self, store: FileStateStore, identity_id: UUID) -> None:
        self.store = store
        self.identity_id = identity_id

    def get_current(self) -> NarrativeDocument | None:
        return self.store.load_narrative(self.identity_id)

    def update(
        self, narrative: NarrativeDocument, *, expected_updated_at: datetime | None = None
    ) -> None:
        if expected_updated_at is not None:
            current = self.store.load_narrative(narrative.identity_id)
            if current is not None and current.updated_at != expected_updated_at:
                from atman.core.exceptions import NarrativePersistenceConflictError

                raise NarrativePersistenceConflictError(
                    "Narrative was modified concurrently since this snapshot was read."
                )
        self.store.save_narrative(narrative)

    def get_history(self) -> list[NarrativeDocument]:
        return []


def _build_session_experience(
    *,
    session_id: UUID,
    when: datetime,
    valence: float,
    intensity: float,
    depth: EmotionalDepth,
    value_label: str,
) -> tuple[SessionExperience, KeyMoment]:
    km = KeyMoment(
        session_id=session_id,
        what_happened=f"E2E test event for {value_label}",
        how_i_felt=FeltSense(
            emotional_valence=valence,
            emotional_intensity=intensity,
            depth=depth,
        ),
        why_it_matters=f"Tests integration around {value_label}",
        values_touched=[value_label, "competence"],
        when=when,
    )
    exp = SessionExperience(
        session_id=session_id,
        timestamp=when,
        key_moment_ids=[km.id],
        avg_emotional_intensity=km.how_i_felt.emotional_intensity,
        has_profound_moment=km.how_i_felt.depth == EmotionalDepth.PROFOUND,
    )
    return exp, km


@pytest.mark.slow
@pytest.mark.e2e
def test_bootstrap_to_deep_reflection_full_lifecycle():
    """SYSTEM_MAP §3 (A–G) end-to-end: bootstrap → 5 experiences → micro/daily/deep → narrative.

    Verifies:
    - bootstrap creates identity + initial snapshot;
    - experiences persist and are retrievable;
    - micro reflection updates the recent layer;
    - daily reflection records a ``DAILY`` event with anchor snapshot;
    - deep reflection records a ``DEEP`` event with health assessment id;
    - narrative renders all three layers.
    """
    with TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        store = FileStateStore(workspace)

        # --- A. Bootstrap identity (§3 A) ------------------------------------
        agent_id = uuid4()
        identity_service = IdentityService(store)
        identity = identity_service.bootstrap_identity(agent_id)
        assert identity.self_description != ""
        assert len(identity.open_questions) >= 1
        snapshots = identity_service.list_snapshots(agent_id)
        assert len(snapshots) == 1
        initial_snapshot_id = snapshots[0].id

        # --- G (skeleton): create initial narrative -------------------------
        narrative_service = NarrativeService(store)
        narrative_service.create_narrative(identity)

        # --- B. Record 5 experiences (§3 B) ---------------------------------
        experience_service = ExperienceService(store)
        today = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
        experiences = []
        session_ids: list[UUID] = []
        labels_depths = [
            ("honesty", EmotionalDepth.MEANINGFUL, 0.4, 0.6),
            ("competence", EmotionalDepth.PROFOUND, 0.2, 0.8),
            ("patience", EmotionalDepth.SURFACE, 0.1, 0.3),
            ("honesty", EmotionalDepth.MEANINGFUL, -0.2, 0.5),
            ("competence", EmotionalDepth.PROFOUND, 0.5, 0.9),
        ]
        # In v3 memory architecture each experience is its own session: persist
        # one Session + one KeyMoment per labelled event so the R3
        # SessionRepository-backed daily reflection sees 5 distinct sessions.
        for i, (label, depth, valence, intensity) in enumerate(labels_depths):
            sid = uuid4()
            session_ids.append(sid)
            when = today + timedelta(minutes=i * 5)
            exp, km = _build_session_experience(
                session_id=sid,
                when=when,
                valence=valence,
                intensity=intensity,
                depth=depth,
                value_label=label,
            )
            experiences.append(exp)
            experience_service.create_experience(exp)
            store.create_session(
                Session(
                    id=sid,
                    agent_id=agent_id,
                    started_at=when,
                    identity_snapshot_id=initial_snapshot_id,
                    status="active",
                )
            )
            store.store_key_moments(sid, [km])

        assert len(experience_service.list_recent(limit=20)) == 5

        # Build adapters for reflection ports.
        exp_repo = _StateStoreExperienceRepo(store)
        session_repo = StateStoreSessionRepository(store, agent_id=agent_id)
        identity_repo = _InMemoryIdentityRepo(store, identity)
        narrative_repo = _NarrativeRepoOverFileStateStore(store, identity.id)

        reflection_model = MockReflectionModel()
        event_store = InMemoryReflectionEventStore()
        pattern_store = InMemoryPatternStore()
        health_store = InMemoryHealthAssessmentStore()

        narrative_revision = NarrativeRevisionService(
            narrative_repo,
            reflection_model,
            narrative_audit=NoOpNarrativeWriteAudit(),
        )

        # --- C. Micro reflection (§3 C) -------------------------------------
        micro = MicroReflectionService(
            experience_repo=exp_repo,
            narrative_revision=narrative_revision,
            event_store=event_store,
        )
        micro_events = [micro.reflect(sid) for sid in session_ids]
        micro_event = micro_events[-1]
        assert micro_event.reflection_level == ReflectionLevel.MICRO
        assert sum(len(e.experiences_analyzed) for e in micro_events) == 5

        narrative_after_micro = store.load_narrative(identity.id)
        assert narrative_after_micro is not None
        assert (
            narrative_after_micro.recent_layer.content
            != "I have just begun. No recent experiences yet to reflect upon."
        )

        # --- D. Daily reflection (§3 D) -------------------------------------
        daily = DailyReflectionService(
            session_repo=session_repo,
            identity_repo=identity_repo,
            pattern_store=pattern_store,
            reflection_model=reflection_model,
            event_store=event_store,
        )
        daily_event = daily.reflect(today)
        assert daily_event.reflection_level == ReflectionLevel.DAILY
        assert len(daily_event.experiences_analyzed) == 5
        assert daily_event.identity_snapshot_id is not None

        # --- E. Deep reflection (§3 E) --------------------------------------
        since = today.replace(hour=0, minute=0, second=0, microsecond=0)
        until = today + timedelta(hours=12)

        deep = DeepReflectionService(
            session_repo=session_repo,
            identity_repo=identity_repo,
            narrative_repo=narrative_repo,
            pattern_store=pattern_store,
            health_store=health_store,
            reflection_model=reflection_model,
            event_store=event_store,
        )
        deep_event = deep.reflect(since, until)
        assert deep_event.reflection_level == ReflectionLevel.DEEP
        assert deep_event.health_assessment_id is not None
        health = health_store.get(deep_event.health_assessment_id)
        assert health is not None
        assert 0.0 <= health.overall_score <= 1.0

        # --- G. Render narrative as markdown (§3 G) -------------------------
        output_path = workspace / "NARRATIVE.md"
        narrative_service.render_to_file(identity.id, output_path)
        text = output_path.read_text(encoding="utf-8")
        assert "# NARRATIVE" in text
        assert "## CORE LAYER" in text
        assert "## RECENT LAYER" in text
