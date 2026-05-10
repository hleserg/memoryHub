"""
Tests for OllamaReflectionModel.
"""

import json
import os
from typing import cast
from unittest.mock import MagicMock, patch

import httpx
import pytest
from pydantic import BaseModel

from atman.adapters.reflection.exceptions import OllamaReflectionError
from atman.adapters.reflection.ollama_reflection_model import (
    OllamaMessage,
    OllamaReflectionModel,
)


class MockOutput(BaseModel):
    """Mock Pydantic model for testing."""

    result: str
    score: float


class TestOllamaReflectionModelInit:
    """Tests for initialization and configuration."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        model = OllamaReflectionModel()
        try:
            assert model.base_url == "http://localhost:11434"
            assert model.model == "qwen3.5:9b"
            assert not model._closed
        finally:
            model.close()

    def test_env_config(self) -> None:
        """Test configuration from environment variables."""
        with patch.dict(
            os.environ,
            {
                "ATMAN_OLLAMA_BASE_URL": "http://custom:8080",
                "ATMAN_OLLAMA_MODEL": "llama3",
            },
        ):
            model = OllamaReflectionModel()
            try:
                assert model.base_url == "http://custom:8080"
                assert model.model == "llama3"
            finally:
                model.close()

    def test_invalid_url_scheme(self) -> None:
        """Test that invalid URL scheme raises ValueError."""
        with patch.dict(os.environ, {"ATMAN_OLLAMA_BASE_URL": "ftp://invalid"}):
            with pytest.raises(ValueError, match="Invalid URL scheme.*ftp"):
                OllamaReflectionModel()

    def test_context_manager(self) -> None:
        """Test context manager closes client properly."""
        with OllamaReflectionModel() as model:
            assert not model._closed
        assert model._closed

    def test_explicit_close(self) -> None:
        """Test explicit close() call."""
        model = OllamaReflectionModel()
        assert not model._closed
        model.close()
        assert model._closed
        # Second close should be idempotent
        model.close()
        assert model._closed

    def test_destructor_warning(self) -> None:
        """Test that __del__ warns about unclosed client."""
        model = OllamaReflectionModel()
        with pytest.warns(ResourceWarning, match="not closed properly"):
            del model


class TestCallWithRetry:
    """Tests for _call_with_retry method."""

    def test_success_first_attempt(self) -> None:
        """Test successful call on first attempt."""
        with OllamaReflectionModel() as model:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.json.return_value = {
                "message": {"content": json.dumps({"result": "success", "score": 0.95})}
            }

            with patch.object(model._client, "post", return_value=mock_response) as mock_post:
                result = model._call_with_retry(
                    [{"role": "user", "content": "test"}],
                    MockOutput,
                )

                assert result.result == "success"
                assert result.score == 0.95
                assert mock_post.call_count == 1

    def test_success_second_attempt(self) -> None:
        """Test successful call on second attempt after JSON error."""
        with OllamaReflectionModel() as model:
            mock_response_fail = MagicMock(spec=httpx.Response)
            mock_response_fail.json.return_value = {"message": {"content": "invalid json{"}}

            mock_response_success = MagicMock(spec=httpx.Response)
            mock_response_success.json.return_value = {
                "message": {"content": json.dumps({"result": "retry_success", "score": 0.8})}
            }

            with patch.object(
                model._client,
                "post",
                side_effect=[mock_response_fail, mock_response_success],
            ) as mock_post:
                result = model._call_with_retry(
                    [{"role": "user", "content": "test"}],
                    MockOutput,
                )

                assert result.result == "retry_success"
                assert result.score == 0.8
                assert mock_post.call_count == 2

    def test_json_decode_error_both_attempts(self) -> None:
        """Test failure after 2 JSON decode errors."""
        with OllamaReflectionModel() as model:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.json.return_value = {"message": {"content": "invalid json{"}}

            with patch.object(model._client, "post", return_value=mock_response) as mock_post:
                with pytest.raises(OllamaReflectionError) as exc_info:
                    model._call_with_retry(
                        [{"role": "user", "content": "test"}],
                        MockOutput,
                    )

                assert exc_info.value.attempts == 2
                assert "invalid json{" in exc_info.value.last_raw
                assert mock_post.call_count == 2

    def test_pydantic_validation_error(self) -> None:
        """Test failure after Pydantic validation errors."""
        with OllamaReflectionModel() as model:
            mock_response = MagicMock(spec=httpx.Response)
            # Missing required 'score' field
            mock_response.json.return_value = {
                "message": {"content": json.dumps({"result": "incomplete"})}
            }

            with patch.object(model._client, "post", return_value=mock_response) as mock_post:
                with pytest.raises(OllamaReflectionError) as exc_info:
                    model._call_with_retry(
                        [{"role": "user", "content": "test"}],
                        MockOutput,
                    )

                assert exc_info.value.attempts == 2
                assert mock_post.call_count == 2

    def test_http_status_error(self) -> None:
        """Test handling of HTTP status errors."""
        with OllamaReflectionModel() as model:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "500 Server Error", request=MagicMock(), response=mock_response
            )

            with patch.object(model._client, "post", return_value=mock_response) as mock_post:
                with pytest.raises(OllamaReflectionError) as exc_info:
                    model._call_with_retry(
                        [{"role": "user", "content": "test"}],
                        MockOutput,
                    )

                assert exc_info.value.attempts == 2
                assert mock_post.call_count == 2

    def test_request_error(self) -> None:
        """Test handling of request errors (network issues)."""
        with OllamaReflectionModel() as model:
            with patch.object(
                model._client,
                "post",
                side_effect=httpx.RequestError("Connection failed"),
            ) as mock_post:
                with pytest.raises(OllamaReflectionError) as exc_info:
                    model._call_with_retry(
                        [{"role": "user", "content": "test"}],
                        MockOutput,
                    )

                assert exc_info.value.attempts == 2
                assert mock_post.call_count == 2

    def test_invalid_message_structure(self) -> None:
        """Test handling of invalid response message structure."""
        with OllamaReflectionModel() as model:
            # message is not a dict
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.json.return_value = {"message": "not a dict"}

            with patch.object(model._client, "post", return_value=mock_response) as mock_post:
                with pytest.raises(OllamaReflectionError) as exc_info:
                    model._call_with_retry(
                        [{"role": "user", "content": "test"}],
                        MockOutput,
                    )

                assert exc_info.value.attempts == 2
                assert mock_post.call_count == 2

    def test_message_is_none(self) -> None:
        """Test handling when message field is None."""
        with OllamaReflectionModel() as model:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.json.return_value = {"message": None}

            with patch.object(model._client, "post", return_value=mock_response):
                with pytest.raises(OllamaReflectionError) as exc_info:
                    model._call_with_retry(
                        [{"role": "user", "content": "test"}],
                        MockOutput,
                    )

            assert exc_info.value.attempts == 2

    def test_payload_structure(self) -> None:
        """Test that payload is constructed correctly."""
        with OllamaReflectionModel() as model:
            model.model = "test-model"
            messages: list[OllamaMessage] = [
                {"role": "system", "content": "You are helpful"},
                {"role": "user", "content": "Hello"},
            ]

            mock_response = MagicMock(spec=httpx.Response)
            mock_response.json.return_value = {
                "message": {"content": json.dumps({"result": "test", "score": 1.0})}
            }

            with patch.object(model._client, "post", return_value=mock_response) as mock_post:
                model._call_with_retry(messages, MockOutput)

                # Verify payload
                call_kwargs = mock_post.call_args[1]
                payload = call_kwargs["json"]
                assert payload["model"] == "test-model"
                assert payload["messages"] == messages
                assert payload["format"] == "json"
                assert payload["stream"] is False
                assert payload["options"]["temperature"] == 0
                assert payload["options"]["seed"] == 42


class TestNotImplementedMethods:
    """Tests for not-yet-implemented reflection methods."""

    def test_generate_reframing_note_raises(self) -> None:
        """Test that generate_reframing_note raises NotImplementedError."""
        with OllamaReflectionModel() as model:
            with pytest.raises(NotImplementedError, match="E21.2"):
                model.generate_reframing_note(MagicMock(), {})

    def test_detect_pattern_raises(self) -> None:
        """Test that detect_pattern raises NotImplementedError."""
        with OllamaReflectionModel() as model:
            with pytest.raises(NotImplementedError, match="E21.2"):
                model.detect_pattern([], {})

    def test_propose_narrative_update_raises(self) -> None:
        """Test that propose_narrative_update raises NotImplementedError."""
        with OllamaReflectionModel() as model:
            with pytest.raises(NotImplementedError, match="E21.2"):
                model.propose_narrative_update(MagicMock(), [], MagicMock())

    def test_assess_health_criterion_raises(self) -> None:
        """Test that assess_health_criterion raises NotImplementedError."""
        with OllamaReflectionModel() as model:
            with pytest.raises(NotImplementedError, match="E21.2"):
                model.assess_health_criterion(MagicMock(), [], MagicMock())
