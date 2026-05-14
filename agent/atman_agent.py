"""
Pydantic AI agent for testing Atman interactions.

This agent is the test user — it talks TO Atman, it is not part of Atman.
Uses its own LLM connection (default: Gemma4 at localhost:8080).
"""

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel

from agent.config import AgentLLMConfig


def create_agent(config: AgentLLMConfig | None = None) -> Agent:
    """
    Creates a Pydantic AI agent backed by Gemma4 (or any configured model).

    This agent is the test user — it talks TO Atman, it is not part of Atman.
    The agent has its own OpenAI client, separate from Atman's internal LLM.

    Args:
        config: Agent LLM configuration. If None, uses defaults from environment.

    Returns:
        Configured Pydantic AI agent ready to interact with Atman.
    """
    cfg = config or AgentLLMConfig()

    # Pass config directly to OpenAIModel without polluting os.environ
    # Note: pydantic-ai's OpenAIModel may not fully support all parameters
    # If this raises at runtime, may need to fall back to env vars or custom client
    model = OpenAIModel(
        model_name=cfg.model,
        base_url=cfg.base_url,  # type: ignore[call-arg]
        api_key=cfg.api_key,  # type: ignore[call-arg]
    )
    return Agent(model=model)
