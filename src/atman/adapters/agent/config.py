"""
Configuration models for Atman Agent.

Defines AgentConfig and ModelConfig for configuring agent behavior
and LLM model settings.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ModelConfig(BaseModel):
    """
    Configuration for the LLM model used by Atman agent.

    Supports different model providers via Pydantic AI model strings:
    - "openai:gpt-4o" for OpenAI
    - "anthropic:claude-3-5-sonnet-20241022" for Anthropic
    - "ollama:llama3.2" for local Ollama
    - "test" for FakeAtmanModel (tests only)
    """

    model: str = Field(
        default="test",
        description="Model identifier in format 'provider:model-name' or 'test' for testing",
    )
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Sampling temperature for model generation",
    )
    max_tokens: int = Field(
        default=2000,
        gt=0,
        description="Maximum tokens for model response",
    )


class AgentConfig(BaseModel):
    """
    Configuration for Atman agent behavior.

    Controls agent execution limits, context truncation, and other
    runtime parameters.
    """

    max_tool_calls: int = Field(
        default=20,
        gt=0,
        description="Maximum tool calls per session (prevents infinite loops)",
    )
    truncate_narrative_recent: int = Field(
        default=2000,
        ge=4,
        description=(
            "Maximum characters for narrative recent_layer in context. "
            "Must be >= 4 so the truncation suffix '...' fits within the budget."
        ),
    )
    truncate_narrative_core: int = Field(
        default=1000,
        ge=4,
        description=(
            "Maximum characters for narrative core_layer in context. "
            "Must be >= 4 so the truncation suffix '...' fits within the budget."
        ),
    )
    enable_experience_search: bool = Field(
        default=True,
        description="Enable search_similar_experiences tool",
    )
    enable_key_moments: bool = Field(
        default=True,
        description="Enable record_key_moment tool",
    )

    model: ModelConfig = Field(default_factory=ModelConfig)
