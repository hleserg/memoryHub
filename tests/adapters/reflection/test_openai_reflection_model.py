"""
Unit tests for OpenAIReflectionModel adapter.

Tests the generic OpenAI-compatible reflection model adapter
without making real HTTP requests.
"""

import json
from uuid import UUID

import httpx
import pytest
import respx

from atman.adapters.reflection.exceptions import OpenAIReflectionError
from atman.adapters.reflection.openai_reflection_model import OpenAIReflectionModel
from atman.config import OpenAILLMConfig
from atman.core.models.experience import SessionExperience
from atman.core.models.reflection import ReframingNoteOutput


def _make_experience() -> SessionExperience:
    """Helper to create minimal valid SessionExperience for testing."""
    return SessionExperience(
        session_id=UUID("00000000-0000-0000-0000-000000000001"),
        key_moment_ids=[UUID("00000000-0000-0000-0000-000000000002")],
        avg_emotional_intensity=0.5,
        has_profound_moment=False,
    )


@respx.mock
def test_generate_reframing_note_success():
    """Test successful reframing with valid JSON response."""
    config = OpenAILLMConfig(
        base_url="http://test-api/v1",
        api_key="test-key",
        model="test-model",
        max_retries=2,
    )
    model = OpenAIReflectionModel(config)

    expected_output = {
        "reflection": "This experience shows growth",
        "reflection_type": "insight",
    }

    respx.post("http://test-api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(expected_output),
                        }
                    }
                ]
            },
        )
    )

    experience = _make_experience()

    result = model.generate_reframing_note(
        experience=experience,
        context={"identity": "I am a persistent learner"},
    )

    assert isinstance(result, ReframingNoteOutput)
    assert result.reflection == "This experience shows growth"
    assert result.reflection_type == "insight"


@respx.mock
def test_retry_on_json_decode_error():
    """Test that the model retries on JSON decode errors."""
    config = OpenAILLMConfig(
        base_url="http://test-api/v1",
        api_key="test-key",
        max_retries=3,
    )
    model = OpenAIReflectionModel(config)

    # First two attempts return invalid JSON, third succeeds
    respx.post("http://test-api/v1/chat/completions").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": "invalid json",
                            }
                        }
                    ]
                },
            ),
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": "still invalid",
                            }
                        }
                    ]
                },
            ),
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "reflection": "Success",
                                        "reflection_type": "growth",
                                    }
                                ),
                            }
                        }
                    ]
                },
            ),
        ]
    )

    experience = _make_experience()

    result = model.generate_reframing_note(
        experience=experience,
        context={"identity": "test"},
    )

    assert isinstance(result, ReframingNoteOutput)
    assert result.reflection == "Success"


@respx.mock
def test_raises_after_max_retries():
    """Test that OpenAIReflectionError is raised after max_retries."""
    config = OpenAILLMConfig(
        base_url="http://test-api/v1",
        api_key="test-key",
        max_retries=2,
    )
    model = OpenAIReflectionModel(config)

    # All attempts return invalid JSON
    respx.post("http://test-api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "invalid json",
                        }
                    }
                ]
            },
        )
    )

    experience = _make_experience()

    with pytest.raises(OpenAIReflectionError) as exc_info:
        model.generate_reframing_note(
            experience=experience,
            context={"identity": "test"},
        )

    assert exc_info.value.attempts == 2
    assert "invalid json" in exc_info.value.last_raw


@respx.mock
def test_http_error_triggers_retry():
    """Test that HTTP errors trigger retry logic."""
    config = OpenAILLMConfig(
        base_url="http://test-api/v1",
        api_key="test-key",
        max_retries=2,
    )
    model = OpenAIReflectionModel(config)

    # First attempt fails with 500, second succeeds
    respx.post("http://test-api/v1/chat/completions").mock(
        side_effect=[
            httpx.Response(500, text="Internal Server Error"),
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "reflection": "Success after retry",
                                        "reflection_type": "resilience",
                                    }
                                ),
                            }
                        }
                    ]
                },
            ),
        ]
    )

    experience = _make_experience()

    result = model.generate_reframing_note(
        experience=experience,
        context={"identity": "test"},
    )

    assert isinstance(result, ReframingNoteOutput)
    assert result.reflection == "Success after retry"


@respx.mock
def test_missing_choices_key_raises_error():
    """Test that missing 'choices' key in response raises KeyError."""
    config = OpenAILLMConfig(
        base_url="http://test-api/v1",
        api_key="test-key",
        max_retries=1,
    )
    model = OpenAIReflectionModel(config)

    # Response missing 'choices' key
    respx.post("http://test-api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"error": "malformed response"},
        )
    )

    experience = _make_experience()

    with pytest.raises(OpenAIReflectionError):
        model.generate_reframing_note(
            experience=experience,
            context={"identity": "test"},
        )


@respx.mock
def test_empty_choices_array_raises_error():
    """Test that empty choices array raises IndexError which is caught and retried."""
    config = OpenAILLMConfig(
        base_url="http://test-api/v1",
        api_key="test-key",
        max_retries=1,
    )
    model = OpenAIReflectionModel(config)

    # Response with empty choices array
    respx.post("http://test-api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"choices": []},
        )
    )

    experience = _make_experience()

    with pytest.raises(OpenAIReflectionError):
        model.generate_reframing_note(
            experience=experience,
            context={"identity": "test"},
        )


def test_config_validation_rejects_zero_retries():
    """Test that max_retries=0 is rejected at config level."""
    with pytest.raises(ValueError, match="max_retries must be >= 1"):
        OpenAILLMConfig(
            base_url="http://test-api/v1",
            api_key="test-key",
            max_retries=0,
        )


def test_config_validation_accepts_one_retry():
    """Test that max_retries=1 is accepted (one attempt, no retries)."""
    config = OpenAILLMConfig(
        base_url="http://test-api/v1",
        api_key="test-key",
        max_retries=1,
    )
    assert config.max_retries == 1


def test_context_manager():
    """Test that OpenAIReflectionModel works as context manager."""
    config = OpenAILLMConfig(
        base_url="http://test-api/v1",
        api_key="test-key",
    )

    with OpenAIReflectionModel(config) as model:
        assert model is not None
        assert hasattr(model, "_client")
