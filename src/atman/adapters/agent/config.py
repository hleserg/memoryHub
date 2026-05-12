"""
Configuration models for Atman Agent.

Defines AgentConfig and ModelConfig for configuring agent behavior
and LLM model settings.
"""

from __future__ import annotations

from typing import Literal

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
    context_limit: int = Field(
        default=8192,
        gt=0,
        description="Maximum context window size for the model",
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
    context_tail_messages: int = Field(
        default=10,
        gt=0,
        description="Number of recent messages to retain in context window",
    )
    session_timeout_minutes: int = Field(
        default=7,
        gt=0,
        description="Session timeout in minutes before automatic termination",
    )
    enable_free_time: bool = Field(
        default=True,
        description="Enable free time processing between sessions",
    )
    show_agent_monologue: bool = Field(
        default=False,
        description="Display agent internal reasoning and thought process",
    )

    model: ModelConfig = Field(default_factory=ModelConfig)

    thinking: bool = Field(
        default=False,
        description=(
            "Enable thinking/reasoning mode for the LLM. "
            "Disabled by default: qwen3 with thinking=True and tool calling "
            "produces broken tool args and returns tool results as JSON text."
        ),
    )
    memory_injection_mode: Literal["system_prompt", "assistant_message", "user_message"] = Field(
        default="assistant_message",
        description=(
            "Where to inject recalled memory context into the agent. "
            "'assistant_message': as agent's own prior output (recommended — feels like recall). "
            "'system_prompt': appended to instructions (requires access to system prompt). "
            "'user_message': as a user-side turn (fallback for restricted host systems)."
        ),
    )
