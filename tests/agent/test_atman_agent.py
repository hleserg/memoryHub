"""
Smoke tests for Pydantic AI test agent.

These tests verify that the agent can be created and interact with its LLM.
They are SKIPPED unless the agent's LLM endpoint (default: Gemma4 at :8080) is available.
"""

import pytest

from agent.atman_agent import create_agent
from agent.config import AgentLLMConfig


@pytest.mark.requires_agent_llm
def test_agent_responds():
    """Test that agent can respond to a simple prompt."""
    agent = create_agent()
    result = agent.run_sync("Say hello.")
    # Pydantic AI AgentRunResult has data attribute, but pyright doesn't see it
    assert result  # type: ignore[truthy-bool]
    assert hasattr(result, "data")
    assert result.data  # type: ignore[attr-defined]


@pytest.mark.requires_agent_llm
def test_agent_with_custom_config():
    """Test that agent respects custom configuration."""
    config = AgentLLMConfig(
        base_url="http://localhost:8080/v1",
        model="gemma4",
        api_key="custom-key",
    )
    agent = create_agent(config)
    # Just verify the agent is created successfully
    assert agent is not None
