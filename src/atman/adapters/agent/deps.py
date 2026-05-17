"""
AtmanDeps - typed dependency container for Atman agent.

This module provides the dependency injection container that holds:
- SessionManager for session lifecycle
- IdentityService for identity management
- ExperienceService for experience storage
- MicroReflectionService for after-session reflection
- StateStore for all persistence

AtmanDeps is passed to agent tools and lifecycle hooks, giving them
access to all necessary services.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from atman.adapters.agent.config import AgentConfig, ModelConfig
    from atman.adapters.observability.in_memory_overload_alert_sink import (
        InMemoryOverloadAlertSink,
    )
    from atman.core.ports.divergence_events import DivergenceEventStore
    from atman.core.ports.memory_guardian import MemoryGuardian
    from atman.core.ports.pending_human_review import PendingHumanReviewInbox
    from atman.core.ports.reflection_request_queue import ReflectionRequestQueue
    from atman.core.ports.state_store import StateStore
    from atman.core.services.ambient_memory_service import AmbientMemoryService
    from atman.core.services.experience_service import ExperienceService
    from atman.core.services.identity_service import IdentityService
    from atman.core.services.passive_memory_injector import PassiveMemoryInjector
    from atman.core.services.reflection_overload_monitor import ReflectionOverloadMonitor
    from atman.core.services.reflection_service import MicroReflectionService
    from atman.core.services.session_manager import SessionManager
    from atman.skills.port import SkillManagerPort


@dataclass(frozen=True)
class AtmanDeps:
    """
    Typed dependency container for Atman agent.

    This container holds all services and state needed by the agent:
    - SessionManager for session lifecycle
    - IdentityService for identity operations
    - ExperienceService for experience storage
    - MicroReflectionService for after-session reflection
    - StateStore for direct state access when needed

    Also tracks the current agent_id and active session_id during execution.

    This is a frozen dataclass to ensure immutability during agent execution.
    """

    session_manager: SessionManager
    identity_service: IdentityService
    experience_service: ExperienceService
    micro_reflection: MicroReflectionService
    state_store: StateStore

    # Runtime context
    agent_id: UUID
    session_id: UUID | None = None

    # Configuration
    max_tool_calls: int = 20
    """Maximum tool calls per session (risk mitigation E26-R4)"""

    truncate_narrative_recent: int = 2000
    """Max chars for narrative recent_layer (risk mitigation E26-R2)"""

    truncate_narrative_core: int = 1000
    """Max chars for narrative core_layer (risk mitigation E26-R2)"""

    model_config: ModelConfig | None = None
    """Model configuration for agent (context limits, temperature, etc.) - E22.3"""

    injected_context: str | None = None
    """Pending memory context for system_prompt injection mode.
    Set via replace(deps, injected_context=...) and consumed by build_instructions()."""

    pending_review_inbox: PendingHumanReviewInbox | None = None
    """Optional pending human review inbox. When provided, the runner surfaces
    unresolved items at session start and exposes the `resolve_pending_review`
    tool. None disables both behaviors."""

    reflection_request_queue: ReflectionRequestQueue | None = None
    """Optional queue for agent-initiated reflection requests. When provided,
    the runner exposes the `request_reflection` tool."""

    passive_memory_injector: PassiveMemoryInjector | None = None
    """Optional RAG pipeline. When present, surfaces relevant facts and key moments
    before each agent.run() call and respects the configured rag_token_budget."""

    skill_manager: SkillManagerPort | None = None
    """Optional skill-loop manager. When None (skills.enabled=false), all skill
    operations are silently skipped. When present, provides pinned-skill bootstrap
    injection, trigger routing, invocation tracking, and reflection processing."""

    divergence_event_store: DivergenceEventStore | None = None
    """Append-only store of :class:`DivergenceEvent` rows persisted from the
    affect pipeline (HLE-29). Exposed on AtmanDeps so the R6
    DivergenceAggregator (Daily reflection) — and any future ad-hoc readers —
    can consume the populated stream without reaching into ``SessionManager``
    internals."""

    reflection_overload_monitor: ReflectionOverloadMonitor | None = None
    """Cadence anomaly check (HLE-30). When wired, the maintenance worker's
    ``reflection_overload_check`` job dispatches to ``monitor.check()`` and
    routes alerts through the wired sink (composite of in-memory + logging
    in the default factory build)."""

    overload_alert_inspect: InMemoryOverloadAlertSink | None = None
    """In-memory tap on the overload-alert fan-out (HLE-30). The factory wires
    this sink as the first child of the composite passed into
    ``reflection_overload_monitor``, so anything emitted by the monitor lands
    here. Admin UIs, debugging endpoints, and integration tests read the
    ``.alerts`` list to introspect captured cadence anomalies without
    reaching into the monitor's private ``_sink`` chain."""

    memory_guardian: MemoryGuardian | None = None
    """Quality-finding scanner (HLE-31 batch scans + HLE-32 inline checks).
    Exposed on AtmanDeps so cli_maintenance / cron workers and any future
    admin endpoints can read findings (``get_unresolved``) and resolve them
    via the same instance the in-memory inline pipeline writes to."""

    ambient_memory: AmbientMemoryService | None = None
    """Entity-anchor parallel RAG (HLE-33). When wired, the runner can call
    ``ambient_memory.compose_injection(user_text, agent_id=agent_id)`` before
    each ``agent.run()`` to surface stance + moments + facts anchored on
    entities named in the message. Independent of the dense
    :class:`PassiveMemoryInjector` path — both can run side-by-side; the
    composer picks one or merges based on configuration."""

    @classmethod
    def from_config(
        cls,
        *,
        config: AgentConfig,
        session_manager: SessionManager,
        identity_service: IdentityService,
        experience_service: ExperienceService,
        micro_reflection: MicroReflectionService,
        state_store: StateStore,
        agent_id: UUID,
        session_id: UUID | None = None,
        pending_review_inbox: PendingHumanReviewInbox | None = None,
        reflection_request_queue: ReflectionRequestQueue | None = None,
        passive_memory_injector: PassiveMemoryInjector | None = None,
        skill_manager: SkillManagerPort | None = None,
        divergence_event_store: DivergenceEventStore | None = None,
        reflection_overload_monitor: ReflectionOverloadMonitor | None = None,
        overload_alert_inspect: InMemoryOverloadAlertSink | None = None,
        memory_guardian: MemoryGuardian | None = None,
        ambient_memory: AmbientMemoryService | None = None,
    ) -> AtmanDeps:
        """
        Build :class:`AtmanDeps` from a validated :class:`AgentConfig`.

        ``AtmanDeps`` is a plain frozen dataclass and accepts any ``int`` for
        its truncation/limit fields, while :class:`AgentConfig` enforces
        ``gt=0`` via Pydantic. Callers should prefer this factory so the
        limits used at runtime are guaranteed to have already been validated,
        instead of constructing :class:`AtmanDeps` directly with raw integers.
        """
        return cls(
            session_manager=session_manager,
            identity_service=identity_service,
            experience_service=experience_service,
            micro_reflection=micro_reflection,
            state_store=state_store,
            agent_id=agent_id,
            session_id=session_id,
            max_tool_calls=config.max_tool_calls,
            truncate_narrative_recent=config.truncate_narrative_recent,
            truncate_narrative_core=config.truncate_narrative_core,
            model_config=config.model,
            pending_review_inbox=pending_review_inbox,
            reflection_request_queue=reflection_request_queue,
            passive_memory_injector=passive_memory_injector,
            skill_manager=skill_manager,
            divergence_event_store=divergence_event_store,
            reflection_overload_monitor=reflection_overload_monitor,
            overload_alert_inspect=overload_alert_inspect,
            memory_guardian=memory_guardian,
            ambient_memory=ambient_memory,
        )
