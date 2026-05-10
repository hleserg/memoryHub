"""Regression tests for OllamaReflectionModelWithPersistence resource cleanup.

Devin Review on PR #414 flagged that the ``__enter__`` / ``__exit__`` /
``close`` methods could leak the PostgreSQL ``ReflectionStore`` connection
or the base model's HTTP client when the other side raised. These tests
exercise both happy-path and failure-path cleanup.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from atman.adapters.reflection.ollama_reflection_model_with_persistence import (
    OllamaReflectionModelWithPersistence,
)


def _build_model(
    base_model: MagicMock, store: MagicMock | None
) -> OllamaReflectionModelWithPersistence:
    """Create the wrapper without invoking the real Ollama / DB constructors."""
    model = OllamaReflectionModelWithPersistence.__new__(OllamaReflectionModelWithPersistence)
    model.base_model = base_model
    model.reflection_store = store
    return model


class TestEnterExitCleanup:
    """Context-manager protocol must not leak resources on partial failures."""

    def test_enter_exit_happy_path_calls_both_sides(self) -> None:
        base_model = MagicMock()
        store = MagicMock()

        model = _build_model(base_model, store)
        with model:
            base_model.__enter__.assert_called_once()
            store.connect.assert_called_once()

        base_model.__exit__.assert_called_once()
        store.close.assert_called_once()

    def test_enter_unwinds_base_model_when_store_connect_fails(self) -> None:
        """If store.connect() raises, the already-entered base_model is closed."""
        base_model = MagicMock()
        store = MagicMock()
        store.connect.side_effect = RuntimeError("db unavailable")

        model = _build_model(base_model, store)

        with pytest.raises(RuntimeError, match="db unavailable"):
            model.__enter__()

        base_model.__enter__.assert_called_once()
        # The wrapper must have unwound the base model on the failed entry.
        base_model.__exit__.assert_called_once_with(None, None, None)

    def test_exit_closes_store_even_if_base_model_exit_raises(self) -> None:
        """``ReflectionStore.close()`` must run even when base_model.__exit__ raises."""
        base_model = MagicMock()
        base_model.__exit__.side_effect = RuntimeError("ollama exit failed")
        store = MagicMock()

        model = _build_model(base_model, store)

        with pytest.raises(RuntimeError, match="ollama exit failed"):
            model.__exit__(None, None, None)

        store.close.assert_called_once()


class TestCloseCleanup:
    """Explicit ``close()`` mirrors __exit__'s guarantees."""

    def test_close_releases_store_when_base_close_raises(self) -> None:
        base_model = MagicMock()
        base_model.close.side_effect = RuntimeError("ollama close failed")
        store = MagicMock()

        model = _build_model(base_model, store)

        with pytest.raises(RuntimeError, match="ollama close failed"):
            model.close()

        store.close.assert_called_once()

    def test_close_without_store_only_closes_base(self) -> None:
        base_model = MagicMock()

        model = _build_model(base_model, store=None)
        model.close()

        base_model.close.assert_called_once()
