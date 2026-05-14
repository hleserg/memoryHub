"""
Pydantic AI agent for testing Atman interactions.

This agent is the test user — it talks TO Atman, it is not part of Atman.
Uses its own LLM connection (default: Gemma4 at localhost:8080).
"""

import os

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

    # OpenAIModel reads OPENAI_BASE_URL and OPENAI_API_KEY from environment
    # Set them temporarily for this agent instance
    os.environ["OPENAI_BASE_URL"] = cfg.base_url
    os.environ["OPENAI_API_KEY"] = cfg.api_key

    model = OpenAIModel(model_name=cfg.model)
    return Agent(model=model)
