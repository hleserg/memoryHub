"""
Core services for Atman.
"""

from atman.core.exceptions import (
    SessionAlreadyFinishedError,
    SessionNotFoundError,
    TooManyActiveSessionsError,
)
from atman.core.services.conflict_detector import ConflictDetector, FactConflict
from atman.core.services.emotional_echo import EchoItem, EmotionalEcho
from atman.core.services.experience_service import ExperienceService
from atman.core.services.identity_service import IdentityService
from atman.core.services.narrative_revision import NarrativeRevisionService
from atman.core.services.narrative_service import NarrativeService
from atman.core.services.passive_memory_injector import PassiveMemoryInjector, SurfacedMemory
from atman.core.services.principle_advisor import PrincipleRevisionAdvisor
from atman.core.services.reflection_service import (
    DailyReflectionService,
    DeepReflectionService,
    MicroReflectionService,
)
from atman.core.services.session_manager import SessionManager
from atman.core.services.session_working_memory import CachedItem, SessionWorkingMemory

__all__ = [
    "CachedItem",
    "ConflictDetector",
    "DailyReflectionService",
    "DeepReflectionService",
    "EchoItem",
    "EmotionalEcho",
    "ExperienceService",
    "FactConflict",
    "IdentityService",
    "MicroReflectionService",
    "NarrativeRevisionService",
    "NarrativeService",
    "PassiveMemoryInjector",
    "PrincipleRevisionAdvisor",
    "SessionAlreadyFinishedError",
    "SessionManager",
    "SessionNotFoundError",
    "SessionWorkingMemory",
    "SurfacedMemory",
    "TooManyActiveSessionsError",
]
