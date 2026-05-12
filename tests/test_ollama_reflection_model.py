"""
Tests for OllamaReflectionModel.

Covers:
- Configuration from env (TestOllamaReflectionModelConfig)
- _call_with_retry retry logic (TestCallWithRetry)
- Four reflection methods: happy path + error propagation (TestReflectionMethods)
- Context manager semantics (TestContextManager)
- respx-based transport tests (TestCallWithRetryRespx)
"""

import json
import os
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
import pytest
import respx
from pydantic import BaseModel

from atman.adapters.reflection.exceptions import OllamaReflectionError
from atman.adapters.reflection.ollama_reflection_model import OllamaReflectionModel
from atman.adapters.reflection.prompts import OllamaMessage
from atman.core.models.experience import EmotionalDepth, FeltSense, KeyMoment, SessionExperience


def _dummy_session_experience() -> SessionExperience:
    km = KeyMoment(
        what_happened="x",
        how_i_felt=FeltSense(
            emotional_valence=0.0,
            emotional_intensity=0.5,
            depth=EmotionalDepth.SURFACE,
        ),
        why_it_matters="y",
    )
    return SessionExperience(
        session_id=uuid4(),
        key_moment_ids=[km.id],
        avg_emotional_intensity=km.how_i_felt.emotional_intensity,
        has_profound_moment=False,
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
        with (
            patch.dict(os.environ, {"ATMAN_OLLAMA_BASE_URL": "ftp://invalid"}),
            pytest.raises(ValueError, match=r"Invalid URL scheme.*ftp"),
        ):
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
        with (
            OllamaReflectionModel() as model,
            patch.object(
                model._client,
                "post",
                side_effect=httpx.RequestError("Connection failed"),
            ) as mock_post,
            pytest.raises(OllamaReflectionError) as exc_info,
        ):
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

            with (
                patch.object(model._client, "post", return_value=mock_response),
                pytest.raises(OllamaReflectionError) as exc_info,
            ):
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


class TestReflectionMethods:
    """Tests for the four reflection methods delegating to _call_with_retry."""

    def _make_mock_response(self, content: str) -> MagicMock:
        """Create a mock httpx.Response returning *content* as message body."""
        resp = MagicMock(spec=httpx.Response)
        resp.json.return_value = {"message": {"content": content}}
        return resp

    def test_generate_reframing_note(self) -> None:
        """Test generate_reframing_note delegates to _call_with_retry."""
        payload = json.dumps({"reflection": "new insight", "reflection_type": "insight"})
        mock_resp = self._make_mock_response(payload)

        with (
            OllamaReflectionModel() as model,
            patch.object(model._client, "post", return_value=mock_resp) as mock_post,
        ):
            result = model.generate_reframing_note(_dummy_session_experience(), {})

            assert result.reflection == "new insight"
            assert result.reflection_type == "insight"
            mock_post.assert_called_once()

    def test_detect_pattern(self) -> None:
        """Test detect_pattern delegates to _call_with_retry."""
        payload = json.dumps(
            {
                "description": "recurring pattern",
                "confidence": 0.7,
                "potential_habit": "",
                "potential_principle": "",
            }
        )
        mock_resp = self._make_mock_response(payload)

        with (
            OllamaReflectionModel() as model,
            patch.object(model._client, "post", return_value=mock_resp) as mock_post,
        ):
            result = model.detect_pattern([], {})

            assert result.description == "recurring pattern"
            assert result.confidence == 0.7
            mock_post.assert_called_once()

    def test_propose_narrative_update(self) -> None:
        """Test propose_narrative_update delegates to _call_with_retry."""
        payload = json.dumps({"body": "updated narrative text"})
        mock_resp = self._make_mock_response(payload)

        with (
            OllamaReflectionModel() as model,
            patch.object(model._client, "post", return_value=mock_resp) as mock_post,
        ):
            result = model.propose_narrative_update(MagicMock(), [], MagicMock())

            assert result.body == "updated narrative text"
            mock_post.assert_called_once()

    def test_assess_health_criterion(self) -> None:
        """Test assess_health_criterion delegates to _call_with_retry."""
        payload = json.dumps(
            {
                "score": 0.75,
                "evidence": ["shows growth"],
                "concerns": ["limited data"],
            }
        )
        mock_resp = self._make_mock_response(payload)

        with (
            OllamaReflectionModel() as model,
            patch.object(model._client, "post", return_value=mock_resp) as mock_post,
        ):
            result = model.assess_health_criterion(MagicMock(), [], MagicMock())

            assert result.score == 0.75
            assert result.evidence == ["shows growth"]
            assert result.concerns == ["limited data"]
            mock_post.assert_called_once()

    # ---- Error propagation tests (2nd per method) ----

    def test_generate_reframing_note_error(self) -> None:
        """Test generate_reframing_note propagates OllamaReflectionError."""
        mock_resp = self._make_mock_response("not json{")

        with (
            OllamaReflectionModel() as model,
            patch.object(model._client, "post", return_value=mock_resp),
            pytest.raises(OllamaReflectionError) as exc_info,
        ):
            model.generate_reframing_note(_dummy_session_experience(), {})

        assert exc_info.value.attempts == 2

    def test_detect_pattern_error(self) -> None:
        """Test detect_pattern propagates OllamaReflectionError."""
        mock_resp = self._make_mock_response("not json{")

        with (
            OllamaReflectionModel() as model,
            patch.object(model._client, "post", return_value=mock_resp),
            pytest.raises(OllamaReflectionError) as exc_info,
        ):
            model.detect_pattern([], {})

        assert exc_info.value.attempts == 2

    def test_propose_narrative_update_error(self) -> None:
        """Test propose_narrative_update propagates OllamaReflectionError."""
        mock_resp = self._make_mock_response("not json{")

        with (
            OllamaReflectionModel() as model,
            patch.object(model._client, "post", return_value=mock_resp),
            pytest.raises(OllamaReflectionError) as exc_info,
        ):
            model.propose_narrative_update(MagicMock(), [], MagicMock())

        assert exc_info.value.attempts == 2

    def test_assess_health_criterion_error(self) -> None:
        """Test assess_health_criterion propagates OllamaReflectionError."""
        mock_resp = self._make_mock_response("not json{")

        with (
            OllamaReflectionModel() as model,
            patch.object(model._client, "post", return_value=mock_resp),
            pytest.raises(OllamaReflectionError) as exc_info,
        ):
            model.assess_health_criterion(MagicMock(), [], MagicMock())

        assert exc_info.value.attempts == 2


class TestCallWithRetryRespx:
    """Tests for _call_with_retry using respx to mock the HTTP transport."""

    def _ollama_response(self, content: str) -> dict[str, object]:
        """Build a minimal Ollama /api/chat response body."""
        return {"message": {"content": content}}

    @respx.mock
    def test_respx_success_first_attempt(self) -> None:
        """Test successful first-attempt via respx transport mock."""
        route = respx.post("http://localhost:11434/api/chat").mock(
            return_value=httpx.Response(
                200,
                json=self._ollama_response(
                    json.dumps({"result": "ok", "score": 0.9}),
                ),
            ),
        )

        with OllamaReflectionModel() as model:
            result = model._call_with_retry(
                [OllamaMessage(role="user", content="test")],
                MockOutput,
            )

        assert result.result == "ok"
        assert result.score == 0.9
        assert route.call_count == 1

    @respx.mock
    def test_respx_retry_on_bad_json(self) -> None:
        """Test retry when first response has bad JSON, second is valid."""
        route = respx.post("http://localhost:11434/api/chat").mock(
            side_effect=[
                httpx.Response(200, json=self._ollama_response("not-json{")),
                httpx.Response(
                    200,
                    json=self._ollama_response(
                        json.dumps({"result": "retried", "score": 0.5}),
                    ),
                ),
            ],
        )

        with OllamaReflectionModel() as model:
            result = model._call_with_retry(
                [OllamaMessage(role="user", content="test")],
                MockOutput,
            )

        assert result.result == "retried"
        assert route.call_count == 2

    @respx.mock
    def test_respx_failure_after_retries(self) -> None:
        """Test OllamaReflectionError after two bad responses via respx."""
        respx.post("http://localhost:11434/api/chat").mock(
            return_value=httpx.Response(200, json=self._ollama_response("bad{")),
        )

        with OllamaReflectionModel() as model:
            with pytest.raises(OllamaReflectionError) as exc_info:
                model._call_with_retry(
                    [OllamaMessage(role="user", content="test")],
                    MockOutput,
                )

            assert exc_info.value.attempts == 2

    @respx.mock
    def test_respx_http_500_then_success(self) -> None:
        """Test retry on HTTP 500 followed by success via respx."""
        route = respx.post("http://localhost:11434/api/chat").mock(
            side_effect=[
                httpx.Response(500, text="Internal Server Error"),
                httpx.Response(
                    200,
                    json=self._ollama_response(
                        json.dumps({"result": "recovered", "score": 1.0}),
                    ),
                ),
            ],
        )

        with OllamaReflectionModel() as model:
            result = model._call_with_retry(
                [OllamaMessage(role="user", content="test")],
                MockOutput,
            )

        assert result.result == "recovered"
        assert route.call_count == 2
