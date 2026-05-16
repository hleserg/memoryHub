"""
Factory for assembling AtmanDeps from a workspace path.

Wires together FileStateStore, SessionManager+AffectDetector,
IdentityService, ExperienceService, MicroReflectionService.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import UUID

from atman.adapters.agent.config import AgentConfig
from atman.adapters.agent.deps import AtmanDeps
from atman.adapters.reflection.state_store_session_repository import (
    StateStoreSessionRepository,
)
from atman.adapters.storage.file_state_store import FileStateStore
from atman.adapters.storage.in_memory_pending_human_review import InMemoryPendingHumanReviewInbox
from atman.adapters.storage.in_memory_reflection_request_queue import InMemoryReflectionRequestQueue
from atman.adapters.storage.in_memory_reflection_store import InMemoryReflectionEventStore

try:
    from atman.affect.detector import AffectDetectorConfig as _AffectDetectorConfig

    _AFFECT_AVAILABLE = True
except ImportError:
    _AffectDetectorConfig = None  # type: ignore[assignment,misc]
    _AFFECT_AVAILABLE = False
from atman.core.models import NarrativeDocument
from atman.core.models.reflection import (
    HealthCriterionOutput,
    NarrativeUpdateOutput,
    PatternDetectionOutput,
    ReframingNoteOutput,
)
from atman.core.narrative_write_audit import NoOpNarrativeWriteAudit
from atman.core.ports.reflection import NarrativeRepository, ReflectionModel
from atman.core.services.experience_service import ExperienceService
from atman.core.services.identity_service import IdentityService
from atman.core.services.narrative_revision import NarrativeRevisionService
from atman.core.services.narrative_service import NarrativeService
from atman.core.services.reflection_service import MicroReflectionService
from atman.core.services.session_manager import SessionManager


class _MockReflectionModel(ReflectionModel):
    def detect_pattern(self, experiences, context):
        return PatternDetectionOutput()

    def generate_reframing_note(self, experience, context):
        return ReframingNoteOutput(reflection="", reflection_type="insight")

    def propose_narrative_update(self, current_narrative, recent_experiences, reflection_level):
        return NarrativeUpdateOutput(body="")

    def assess_health_criterion(self, identity, experiences, criterion):
        return HealthCriterionOutput(score=0.5, evidence=[], concerns=[])


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
    session_manager = SessionManager(state_store, **affect_kwargs, workspace=workspace)

    narrative_revision = NarrativeRevisionService(
        narrative_repo=_NarrativeAdapter(state_store),
        reflection_model=_MockReflectionModel(),
        narrative_audit=NoOpNarrativeWriteAudit(),
    )
    micro_reflection = MicroReflectionService(
        session_repo=StateStoreSessionRepository(state_store, agent_id=agent_id),
        narrative_revision=narrative_revision,
        event_store=InMemoryReflectionEventStore(),
    )

    # Build optional RAG pipeline when ATMAN_LINGUISTIC_ENABLED=true.
    # Uses the configured embedding backend (ollama/flag) and the same
    # state_store that the session will write to.
    passive_memory_injector = None
    if os.getenv("ATMAN_LINGUISTIC_ENABLED", "false").lower() == "true":
        from atman.config import build_embedding_adapter
        from atman.config import build_memory_backend as _build_mem
        from atman.core.services.passive_memory_injector import PassiveMemoryInjector

        try:
            _embedding = build_embedding_adapter()
            _factual_memory = _build_mem()
            passive_memory_injector = PassiveMemoryInjector(
                embedding=_embedding,
                factual_memory=_factual_memory,
                state_store=state_store,
            )
        except Exception:
            import logging as _logging

            _logging.getLogger(__name__).warning(
                "Failed to build PassiveMemoryInjector — RAG disabled", exc_info=True
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
        pending_review_inbox=InMemoryPendingHumanReviewInbox(),
        reflection_request_queue=InMemoryReflectionRequestQueue(),
        passive_memory_injector=passive_memory_injector,
    )

    return deps, session_manager, state_store
