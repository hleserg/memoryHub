"""
Core ports для Atman.
"""

from atman.core.ports.embedding import EmbeddingPort
from atman.core.ports.memory_backend import FactualMemory
from atman.core.ports.memory_usage_log import MemoryUsageLog, MemoryUsageRecord, UsageType
from atman.core.ports.pending_human_review import PendingHumanReviewInbox
from atman.core.ports.reflection import (
    ExperienceRepository,
    HealthAssessmentStore,
    IdentityRepository,
    NarrativeRepository,
    NarrativeWriteAuditPort,
    PatternStore,
    ReflectionEventPersistenceObserver,
    ReflectionEventStore,
    ReflectionModel,
)
from atman.core.ports.reflection_overload_alert import (
    ReflectionOverloadAlertSink,
    ReflectionOverloadSeverity,
)
from atman.core.ports.reflection_request_queue import ReflectionRequestQueue
from atman.core.ports.self_applied_changes import SelfAppliedChangeStore
from atman.core.ports.state_store import (
    DateRangeQuery,
    DepthQuery,
    ExperienceQuery,
    FactRefsContainsQuery,
    SessionExperienceQuery,
    StateStore,
    ValuesTouchedQuery,
)

__all__ = [
    "DateRangeQuery",
    "DepthQuery",
    "EmbeddingPort",
    "ExperienceQuery",
    "ExperienceRepository",
    "FactRefsContainsQuery",
    "FactualMemory",
    "HealthAssessmentStore",
    "IdentityRepository",
    "MemoryUsageLog",
    "MemoryUsageRecord",
    "NarrativeRepository",
    "NarrativeWriteAuditPort",
    "PatternStore",
    "PendingHumanReviewInbox",
    "ReflectionEventPersistenceObserver",
    "ReflectionEventStore",
    "ReflectionModel",
    "ReflectionOverloadAlertSink",
    "ReflectionOverloadSeverity",
    "ReflectionRequestQueue",
    "SelfAppliedChangeStore",
    "SessionExperienceQuery",
    "StateStore",
    "UsageType",
    "ValuesTouchedQuery",
]
