"""
Ollama implementation of ReflectionModel.

Uses Ollama's local LLM API for structured generation during reflection.
"""

import json
import os
import warnings
from typing import Any, TypeVar
from urllib.parse import urlparse

import httpx
import pydantic

from atman.adapters.reflection.exceptions import OllamaReflectionError
from atman.adapters.reflection.prompts import (
    OllamaMessage,
    build_health_messages,
    build_narrative_messages,
    build_pattern_messages,
    build_reframing_messages,
)
from atman.core.models.experience import SessionExperience
from atman.core.models.identity import Identity
from atman.core.models.narrative import NarrativeDocument
from atman.core.models.reflection import (
    HealthCriterionOutput,
    JahodaCriterion,
    NarrativeUpdateOutput,
    PatternDetectionOutput,
    ReflectionLevel,
    ReframingNoteOutput,
)
from atman.core.ports.reflection import ReflectionModel

T = TypeVar("T", bound=pydantic.BaseModel)


class OllamaReflectionModel(ReflectionModel):
    """
    Ollama-backed implementation of ReflectionModel.

    Reads configuration from environment:
    - ATMAN_OLLAMA_BASE_URL (default: http://localhost:11434)
    - ATMAN_OLLAMA_MODEL (default: qwen3.5:9b)

    Note: Uses synchronous HTTP client to match the synchronous ReflectionModel port.
    Call close() when done to release resources, or use as context manager.
    """

    def __init__(self) -> None:
        """
        Initialize OllamaReflectionModel with configuration from environment.

        Raises:
            ValueError: If ATMAN_OLLAMA_BASE_URL has invalid scheme
        """
        base_url = os.getenv("ATMAN_OLLAMA_BASE_URL", "http://localhost:11434")
        parsed_url = urlparse(base_url)
        if parsed_url.scheme not in ("http", "https"):
            raise ValueError(
                f"Invalid URL scheme in ATMAN_OLLAMA_BASE_URL: {parsed_url.scheme}. "
                "Expected 'http' or 'https'."
            )

        self.base_url = base_url
        self.model = os.getenv("ATMAN_OLLAMA_MODEL", "qwen3.5:9b")
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(60.0, connect=5.0),
        )
        self._closed = False

    def _call_with_retry(
        self,
        messages: list[OllamaMessage],
        output_model: type[T],
    ) -> T:
        """
        Call Ollama API with retry on parsing failures.

        Args:
            messages: List of message dicts with "role" and "content"
            output_model: Pydantic model to parse response into

        Returns:
            Parsed structured output

        Raises:
            OllamaReflectionError: After 2 failed attempts
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "format": "json",
            "stream": False,
            "options": {
                "temperature": 0,
                "seed": 42,
            },
        }

        last_raw = ""

        for attempt in range(2):
            attempts = attempt + 1
            try:
                response = self._client.post("/api/chat", json=payload)
                response.raise_for_status()
                response_json = response.json()

                message = response_json.get("message")
                if not isinstance(message, dict):
                    raise ValueError(f"Unexpected message type: {type(message).__name__}")

                message_content = message.get("content", "")
                last_raw = message_content

                parsed_json = json.loads(message_content)
                return output_model.model_validate(parsed_json)
            except (
                json.JSONDecodeError,
                pydantic.ValidationError,
                httpx.HTTPStatusError,
                httpx.RequestError,
                ValueError,
            ):
                if attempt == 1:
                    raise OllamaReflectionError(attempts=attempts, last_raw=last_raw) from None
                continue

        raise AssertionError("Unreachable: loop should exit via return or raise")

    def close(self) -> None:
        """Close the HTTP client and release resources."""
        if not self._closed:
            self._client.close()
            self._closed = True

    def __enter__(self) -> "OllamaReflectionModel":
        """Context manager entry."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Context manager exit."""
        self.close()

    def __del__(self) -> None:
        """Destructor to warn about unclosed client."""
        if hasattr(self, "_closed") and not self._closed:
            warnings.warn(
                "OllamaReflectionModel was not closed properly. "
                "Use 'with OllamaReflectionModel() as model:' or call close() explicitly.",
                ResourceWarning,
                stacklevel=2,
            )

    def generate_reframing_note(
        self,
        experience: SessionExperience,
        context: dict[str, str],
    ) -> ReframingNoteOutput:
        """Generate a reframing note for an experience via Ollama."""
        messages = build_reframing_messages(experience, context)
        return self._call_with_retry(messages, ReframingNoteOutput)

    def detect_pattern(
        self,
        experiences: list[SessionExperience],
        context: dict[str, str],
    ) -> PatternDetectionOutput:
        """Detect and describe a pattern across experiences via Ollama."""
        messages = build_pattern_messages(experiences, context)
        return self._call_with_retry(messages, PatternDetectionOutput)

    def propose_narrative_update(
        self,
        current_narrative: NarrativeDocument,
        recent_experiences: list[SessionExperience],
        reflection_level: ReflectionLevel,
    ) -> NarrativeUpdateOutput:
        """Propose an update to the narrative via Ollama."""
        messages = build_narrative_messages(
            current_narrative,
            recent_experiences,
            reflection_level,
        )
        return self._call_with_retry(messages, NarrativeUpdateOutput)

    def assess_health_criterion(
        self,
        identity: Identity,
        experiences: list[SessionExperience],
        criterion: JahodaCriterion,
    ) -> HealthCriterionOutput:
        """Assess one Jahoda health criterion via Ollama."""
        messages = build_health_messages(identity, experiences, criterion)
        return self._call_with_retry(messages, HealthCriterionOutput)
