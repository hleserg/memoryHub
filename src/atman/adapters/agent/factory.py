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
    from atman.affect.detector import AffectDetector as _AffectDetector
    from atman.affect.detector import AffectDetectorConfig as _AffectDetectorConfig

    _AFFECT_AVAILABLE = True
except ImportError:
    _AffectDetector = None  # type: ignore[assignment,misc]
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
    def detect_pattern(self, experiences, context, *, key_moments_by_session=None):
        return PatternDetectionOutput()

    def generate_reframing_note(self, experience, context, *, key_moments_by_session=None):
        return ReframingNoteOutput(reflection="", reflection_type="insight")

    def propose_narrative_update(
        self,
        current_narrative,
        recent_experiences,
        reflection_level,
        *,
        key_moments_by_session=None,
    ):
        return NarrativeUpdateOutput(body="")

    def assess_health_criterion(
        self, identity, experiences, criterion, *, key_moments_by_session=None
    ):
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

    # Maintenance queue + post-write scheduler (HLE-27): enqueue mREBEL +
    # lingvo enrichment jobs after every KeyMoment write.
    #
    # The queue is the in-memory variant by default — sufficient for
    # single-process dev runs. **Important:** nothing in build_deps spawns a
    # MaintenanceWorker drain; the queue accumulates until an out-of-process
    # consumer runs `python -m atman.cli_maintenance run --loop`. Production
    # Postgres deploys swap the queue for `PostgresMaintenanceQueue` and run
    # a long-lived worker pod against it. In CI / unit tests the queue is
    # introspected directly — there's no orphan-worker requirement.
    from atman.adapters.maintenance.in_memory_queue import InMemoryMaintenanceQueue
    from atman.core.services.post_write_scheduler import PostWriteScheduler

    maintenance_queue = InMemoryMaintenanceQueue()
    post_write_scheduler = PostWriteScheduler(maintenance_queue)

    # HLE-29: divergence pipeline. The detector turns LinguisticAnalysis into
    # DivergenceEvent rows; the store persists them so R6 DivergenceAggregator
    # (Daily reflection) can read populated history later.
    #
    # Analyzer selection (Devin Review ANALYSIS_0002, PR #592):
    # * When the `linguistic` extra is installed AND ATMAN_LINGUISTIC_ENABLED=true,
    #   instantiate the real GLiNER+MiniLM analyzer. It lazy-loads models on
    #   first call so import is cheap.
    # * Otherwise the NoOp analyzer keeps the pipeline alive but emits no
    #   divergence signals — that is the correct dev-mode behaviour.
    from atman.adapters.linguistic.noop_adapter import NoOpLinguisticAnalyzer
    from atman.adapters.memory.in_memory_divergence_events import (
        InMemoryDivergenceEventStore,
    )
    from atman.core.ports.linguistic import LinguisticAnalyzer as _LinguisticAnalyzer
    from atman.core.services.divergence_detector import DivergenceDetector

    _linguistic_enabled = os.getenv("ATMAN_LINGUISTIC_ENABLED", "false").lower() == "true"
    _affect_linguistic: _LinguisticAnalyzer = NoOpLinguisticAnalyzer()
    if _linguistic_enabled:
        try:
            from atman.adapters.linguistic.gliner_minilm_adapter import (  # type: ignore[import-not-found]
                _GLINER_AVAILABLE,
                _TRANSFORMERS_AVAILABLE,
                GLiNERPlusMiniLMAdapter,
            )

            if _GLINER_AVAILABLE and _TRANSFORMERS_AVAILABLE:
                _affect_linguistic = GLiNERPlusMiniLMAdapter()
        except Exception:
            import logging as _logging

            _logging.getLogger(__name__).warning(
                "Falling back to NoOpLinguisticAnalyzer — GLiNER+MiniLM adapter unavailable",
                exc_info=True,
            )
    _divergence_detector = DivergenceDetector(agent_id)
    _divergence_event_store = InMemoryDivergenceEventStore()

    # HLE-52: build the affect adapter here (composition root) and inject via
    # AffectPort so SessionManager never imports the concrete implementation.
    session_manager = SessionManager(
        state_store,
        workspace=workspace,
        post_write_scheduler=post_write_scheduler,
    )
    if _AFFECT_AVAILABLE:
        assert _AffectDetector is not None and _AffectDetectorConfig is not None
        session_manager.attach_affect(
            _AffectDetector(
                _AffectDetectorConfig(),
                workspace=workspace,
                append_moment=session_manager.append_key_moment,
                linguistic_analyzer=_affect_linguistic,
                divergence_detector=_divergence_detector,
                divergence_event_store=_divergence_event_store,
            )
        )

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

    # HLE-30: share the reflection event store between the reflection service
    # (writer) and the overload monitor (reader). The monitor is exposed on
    # AtmanDeps so cli_maintenance / cron jobs can pick it up to drive the
    # reflection_overload_check dispatch.
    _reflection_event_store = InMemoryReflectionEventStore()
    micro_reflection = MicroReflectionService(
        session_repo=StateStoreSessionRepository(state_store, agent_id=agent_id),
        narrative_revision=narrative_revision,
        event_store=_reflection_event_store,
        skill_manager=skill_manager,
    )

    from atman.adapters.observability.composite_overload_alert_sink import (
        CompositeOverloadAlertSink,
    )
    from atman.adapters.observability.in_memory_overload_alert_sink import (
        InMemoryOverloadAlertSink,
    )
    from atman.adapters.observability.logging_overload_alert_sink import (
        LoggingOverloadAlertSink,
    )
    from atman.core.services.reflection_overload_monitor import ReflectionOverloadMonitor

    _overload_sink_inmem = InMemoryOverloadAlertSink()
    _overload_sink = CompositeOverloadAlertSink([_overload_sink_inmem, LoggingOverloadAlertSink()])
    _overload_monitor = ReflectionOverloadMonitor(
        event_store=_reflection_event_store,
        alert_sink=_overload_sink,
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
        divergence_event_store=_divergence_event_store,
        reflection_overload_monitor=_overload_monitor,
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
