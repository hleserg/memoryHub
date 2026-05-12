"""
Factory for assembling AtmanDeps from a workspace path.

Wires together FileStateStore, SessionManager+AffectDetector,
IdentityService, ExperienceService, MicroReflectionService.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import UUID

from atman.adapters.agent.config import AgentConfig
from atman.adapters.agent.deps import AtmanDeps
from atman.adapters.storage.file_state_store import FileStateStore
from atman.adapters.storage.in_memory_reflection_store import InMemoryReflectionEventStore

try:
    from atman.affect.detector import AffectDetectorConfig as _AffectDetectorConfig

    _AFFECT_AVAILABLE = True
except ImportError:
    _AffectDetectorConfig = None  # type: ignore[assignment,misc]
    _AFFECT_AVAILABLE = False
from atman.core.models import NarrativeDocument
from atman.core.models.experience import ReframingNoteAppendResult
from atman.core.models.reflection import (
    HealthCriterionOutput,
    NarrativeUpdateOutput,
    PatternDetectionOutput,
    ReframingNoteOutput,
)
from atman.core.narrative_write_audit import NoOpNarrativeWriteAudit
from atman.core.ports.reflection import ExperienceRepository, NarrativeRepository, ReflectionModel
from atman.core.ports.state_store import DateRangeQuery, SessionExperienceQuery
from atman.core.services.experience_service import ExperienceService
from atman.core.services.identity_service import IdentityService
from atman.core.services.narrative_service import NarrativeService
from atman.core.services.narrative_revision import NarrativeRevisionService
from atman.core.services.reflection_service import MicroReflectionService
from atman.core.services.session_manager import SessionManager

_EXPERIENCE_LIMIT = 1000


class _MockReflectionModel(ReflectionModel):
    def detect_pattern(self, experiences, context):
        return PatternDetectionOutput()

    def generate_reframing_note(self, experience, context):
        return ReframingNoteOutput(reflection="", reflection_type="insight")

    def propose_narrative_update(self, current_narrative, recent_experiences, reflection_level):
        return NarrativeUpdateOutput(body="")

    def assess_health_criterion(self, identity, experiences, criterion):
        return HealthCriterionOutput(score=0.5, evidence=[], concerns=[])


class _ExperienceAdapter(ExperienceRepository):
    def __init__(self, store: FileStateStore):
        self._s = store

    def get(self, experience_id):
        r = self._s.get_experience(experience_id)
        return r.experience if r else None

    def get_all(self):
        return [r.experience for r in self._s.list_recent_experiences(limit=_EXPERIENCE_LIMIT)]

    def get_by_session(self, session_id):
        return [
            r.experience
            for r in self._s.search_experiences(
                SessionExperienceQuery(session_id), limit=_EXPERIENCE_LIMIT
            )
        ]

    def get_in_range(self, start: datetime, end: datetime):
        return [
            r.experience
            for r in self._s.search_experiences(DateRangeQuery(start, end), limit=_EXPERIENCE_LIMIT)
        ]

    def get_recent(self, limit=10):
        return [r.experience for r in self._s.list_recent_experiences(limit=limit)]

    def update(self, experience):
        raise NotImplementedError

    def add_reframing_note(self, experience_id, note):
        # Check for duplicate before calling store
        if note.triggered_by:
            record = self._s.get_experience(experience_id)
            if record is None:
                return ReframingNoteAppendResult.EXPERIENCE_NOT_FOUND
            if any(n.triggered_by == note.triggered_by for n in record.experience.reframing_notes):
                return ReframingNoteAppendResult.DUPLICATE_TRIGGERED_BY

        count_before = 0
        if note.triggered_by:
            rec0 = self._s.get_experience(experience_id)
            if rec0 is None:
                return ReframingNoteAppendResult.EXPERIENCE_NOT_FOUND
            count_before = len(rec0.experience.reframing_notes)

        result = self._s.add_reframing_note(experience_id, note)
        if result is None:
            return ReframingNoteAppendResult.EXPERIENCE_NOT_FOUND

        # FileStateStore returns the existing record on duplicate triggered_by without
        # appending; map that to DUPLICATE_TRIGGERED_BY instead of STORED.
        if note.triggered_by and len(result.experience.reframing_notes) == count_before:
            return ReframingNoteAppendResult.DUPLICATE_TRIGGERED_BY

        return ReframingNoteAppendResult.STORED


class _NarrativeAdapter(NarrativeRepository):
    def __init__(self, store: FileStateStore):
        self._s = store

    def get_current(self):
        p = self._s.narrative_path
        if not p.exists():
            return None
        with open(p, encoding="utf-8") as f:
            return NarrativeDocument.model_validate(json.load(f))

    def get_history(self):
        return []

    def update(self, narrative, *, expected_updated_at=None):
        self._s.save_narrative(narrative, expected_updated_at=expected_updated_at)

    def save(self, narrative):
        return self._s.save_narrative(narrative)


def build_deps(
    workspace: Path,
    agent_id: UUID,
    config: AgentConfig | None = None,
) -> tuple[AtmanDeps, SessionManager, FileStateStore]:
    """Assemble all services and return AtmanDeps ready for a session."""
    if config is None:
        config = AgentConfig()

    workspace.mkdir(parents=True, exist_ok=True)
    state_store = FileStateStore(workspace=workspace)
    identity_service = IdentityService(state_store)
    narrative_service = NarrativeService(state_store)

    identity = state_store.load_identity(agent_id)
    if identity is None:
        identity = identity_service.bootstrap_identity(agent_id)
    if state_store.load_narrative(identity.id) is None:
        narrative_service.create_narrative(identity)

    affect_kwargs: dict = {}
    if _AFFECT_AVAILABLE:
        assert _AffectDetectorConfig is not None
        affect_kwargs = {
            "affect_workspace": workspace,
            "affect_config": _AffectDetectorConfig(),
        }
    session_manager = SessionManager(state_store, workspace=workspace, **affect_kwargs)

    narrative_revision = NarrativeRevisionService(
        narrative_repo=_NarrativeAdapter(state_store),
        reflection_model=_MockReflectionModel(),
        narrative_audit=NoOpNarrativeWriteAudit(),
    )
    micro_reflection = MicroReflectionService(
        experience_repo=_ExperienceAdapter(state_store),
        narrative_revision=narrative_revision,
        event_store=InMemoryReflectionEventStore(),
    )

    deps = AtmanDeps.from_config(
        config=config,
        session_manager=session_manager,
        identity_service=identity_service,
        experience_service=ExperienceService(state_store),
        micro_reflection=micro_reflection,
        state_store=state_store,
        agent_id=agent_id,
        session_id=None,
    )

    return deps, session_manager, state_store
