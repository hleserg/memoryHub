"""
Atman Agent Adapter - Pydantic AI integration layer.

This adapter connects SessionManager, IdentityStore, and ReflectionEngine
to a real LLM via Pydantic AI. It provides:

1. AtmanDeps - typed dependency container
2. AtmanAgent - Pydantic AI Agent with dynamic instructions from identity
3. Agent tools for recording and querying experience
4. Session lifecycle hooks for experience transfer and reflection
"""

from atman.adapters.agent.config import AgentConfig, ModelConfig
from atman.adapters.agent.deps import AtmanDeps
from atman.adapters.agent.instructions import build_instructions
from atman.adapters.agent.tools import (
    log_experience,
    record_key_moment,
    restart_session,
    wait_session,
)

__all__ = [
    "AgentConfig",
    "AtmanDeps",
    "ModelConfig",
    "build_instructions",
    "log_experience",
    "record_key_moment",
    "restart_session",
    "wait_session",
]
