"""Tests for reflection model factory wiring."""

import pytest

from atman.adapters.reflection import MockReflectionModel, get_reflection_model
from atman.adapters.reflection.openai_reflection_model import OpenAIReflectionModel


def test_get_reflection_model_defaults_to_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ATMAN_REFLECTION_BACKEND", raising=False)

    model = get_reflection_model()

    assert isinstance(model, OpenAIReflectionModel)
    model.close()


def test_get_reflection_model_uses_mock_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATMAN_REFLECTION_BACKEND", "mock")

    model = get_reflection_model()

    assert isinstance(model, MockReflectionModel)


def test_get_reflection_model_rejects_unimplemented_anthropic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATMAN_REFLECTION_BACKEND", "anthropic")

    with pytest.raises(NotImplementedError, match="Anthropic backend"):
        get_reflection_model()


def test_get_reflection_model_rejects_unknown_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATMAN_REFLECTION_BACKEND", "missing")

    with pytest.raises(ValueError, match="Unknown reflection backend"):
        get_reflection_model()
