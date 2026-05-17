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
    # Build optional RAG pipeline when ATMAN_LINGUISTIC_ENABLED=true.
    # Uses the configured embedding backend (ollama/flag) and the same
    # state_store that the session will write to.
    passive_memory_injector = None
    _embedding_adapter = None
    if os.getenv("ATMAN_LINGUISTIC_ENABLED", "false").lower() == "true":
        from atman.config import build_embedding_adapter
        from atman.config import build_memory_backend as _build_mem
        from atman.core.services.passive_memory_injector import PassiveMemoryInjector

        try:
            from atman.adapters.linguistic.noop_adapter import NoOpLinguisticAnalyzer
            from atman.adapters.memory.bm25_embedding import BM25EmbeddingAdapter
            from atman.adapters.memory.noop_reranker import NoOpReranker

            _embedding_adapter = build_embedding_adapter()
            _factual_memory = _build_mem()
            # BM25 is zero-dependency and provides a second retrieval signal
            # fused with the dense embedding via Reciprocal Rank Fusion. It
            # rescues exact lexical matches that dense encoders can rank low.
            _bm25 = BM25EmbeddingAdapter()

            # Ambient mode requires both a LinguisticAnalyzer and a
            # MemoryReranker on the PMI. Try the BGE cross-encoder first
            # (linguistic extra); fall back to NoOp when FlagEmbedding /
            # model assets are unavailable so the ambient path stays
            # reachable in lean deployments.
            _linguistic: object = NoOpLinguisticAnalyzer()
            try:
                from atman.adapters.memory.bge_reranker import BgeReranker

                _reranker: object = BgeReranker()
            except Exception:
                _reranker = NoOpReranker()

            passive_memory_injector = PassiveMemoryInjector(
                embedding=_embedding_adapter,
                factual_memory=_factual_memory,
                state_store=state_store,
                bm25=_bm25,
                linguistic_analyzer=_linguistic,
                memory_reranker=_reranker,
            )
        except Exception:
            import logging as _logging

            _logging.getLogger(__name__).warning(
                "Failed to build PassiveMemoryInjector — RAG disabled", exc_info=True
            )

    # Build optional skill-loop when skills.enabled=true (default).
    #
    # IMPORTANT: skill_manager must be built BEFORE MicroReflectionService so
    # the reflection hook (process_session_skills) actually fires. If you move
    # this block after the MicroReflectionService construction, the hook
    # becomes dead code — see PR #572 Devin review.
    skill_manager = _build_skill_manager(
        agent_id=agent_id,
        embedding_adapter=_embedding_adapter,
    )

    micro_reflection = MicroReflectionService(
        session_repo=StateStoreSessionRepository(state_store, agent_id=agent_id),
        narrative_revision=narrative_revision,
        event_store=InMemoryReflectionEventStore(),
        skill_manager=skill_manager,
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
        skill_manager=skill_manager,
    )

    return deps, session_manager, state_store


def _build_skill_manager(agent_id: UUID, embedding_adapter):
    """Assemble SkillManager with graceful fallback.

    Behaviour, in order of preference, when ``settings.skills.enabled`` is true:

    1. ``PostgresSkillStore`` if PostgreSQL is configured and reachable.
    2. ``InMemorySkillStore`` fallback so local/file-based development still
       starts a real (in-process) skill-loop. Per AGENTS.md, the project must
       run without external services; failing to connect to PostgreSQL should
       degrade, not crash.
    3. ``None`` (skill-loop disabled) if both stores fail to construct.

    All branches return at most one log line on the warning level; no
    exception is allowed to escape.
    """
    from atman.config import settings as _settings

    if not _settings.skills.enabled:
        return None

    import logging as _logging
    from pathlib import Path as _Path

    from atman.skills.manager import SkillManager
    from atman.skills.projection import PydanticAgentProjector
    from atman.skills.retriever import SkillRetriever

    log = _logging.getLogger(__name__)

    skill_store: object | None = None
    try:
        from atman.skills.postgres_store import PostgresSkillStore

        skill_store = PostgresSkillStore(db_url=_settings.database_url, agent_id=agent_id)
    except Exception:
        log.info(
            "PostgresSkillStore unavailable — falling back to in-memory skill store. "
            "Set ATMAN_SKILLS_ENABLED=false to silence this notice.",
            exc_info=True,
        )

    if skill_store is None:
        try:
            from atman.skills.in_memory_store import InMemorySkillStore

            skill_store = InMemorySkillStore()
        except Exception:
            log.warning("Failed to build any SkillStore — skill-loop disabled", exc_info=True)
            return None

    try:
        retriever = SkillRetriever(store=skill_store, embedding=embedding_adapter)
        return SkillManager(
            store=skill_store,
            retriever=retriever,
            projector=PydanticAgentProjector(),
            config=_settings.skills,
            agents_root=_Path(_settings.skills.skills_root).expanduser(),
        )
    except Exception:
        log.warning("Failed to build SkillManager — skill-loop disabled", exc_info=True)
        return None
