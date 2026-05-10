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
    from atman.core.ports.state_store import StateStore
    from atman.core.services.experience_service import ExperienceService
    from atman.core.services.identity_service import IdentityService
    from atman.core.services.reflection_service import MicroReflectionService
    from atman.core.services.session_manager import SessionManager


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
