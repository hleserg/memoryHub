from __future__ import annotations

import importlib.util
from importlib.machinery import ModuleSpec

import pytest


@pytest.fixture(autouse=True)
def _patch_eval_canary(monkeypatch: pytest.MonkeyPatch) -> None:
    """Allow importing atman.eval tests even without full eval extras."""
    original_find_spec = importlib.util.find_spec

    def patched_find_spec(name: str, package: str | None = None) -> ModuleSpec | None:
        if name == "alembic":
            spec = original_find_spec(name, package)
            if spec is not None:
                return spec
            return ModuleSpec(name="alembic", loader=None)
        return original_find_spec(name, package)

    monkeypatch.setattr(importlib.util, "find_spec", patched_find_spec)
