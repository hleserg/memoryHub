"""
LLM configuration for the Pydantic AI test agent.

This config is SEPARATE from Atman's internal LLM config.
The agent uses these settings to connect to its own LLM (default: Gemma4 at :8080).
"""

import os
from dataclasses import dataclass, field


@dataclass
class AgentLLMConfig:
    """
    LLM connection config for the Pydantic AI test agent.
    Separate from Atman's internal LLM config.
    Default: local Gemma4 via llama-server at :8080.
    """

    base_url: str = field(
        default_factory=lambda: os.getenv("AGENT_LLM_BASE_URL", "http://localhost:8080/v1")
    )
    api_key: str = field(default_factory=lambda: os.getenv("AGENT_LLM_API_KEY", "dummy"))
    model: str = field(default_factory=lambda: os.getenv("AGENT_LLM_MODEL", "gemma4"))
