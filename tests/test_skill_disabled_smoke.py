"""HLE-41 smoke tests — agent boots cleanly when the skill-loop is disabled.

The skill-loop is meant to be fully optional. These tests pin down that
guarantee so a regression that adds an unconditional ``deps.skill_manager.*``
call (or that re-introduces a Postgres lookup on bootstrap) fails fast.

Covered:

* env-var override ``ATMAN_SKILLS_ENABLED=false`` disables the loop
* ``settings.skills.enabled = False`` disables the loop
* ``build_deps`` returns ``skill_manager=None`` and does NOT touch Postgres
* ``build_instructions`` is safe to call with ``skill_manager=None``
* Agent tool registration in :mod:`atman.skills.agent_tools` is opt-in:
  there is no module-level side effect, so the four skill tools never end up
  on an agent unless the runner wires them explicitly.
* :meth:`MicroReflectionService.reflect` is a no-op for the skill hook when
  ``skill_manager`` is unset or ``agent_id`` is None.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest


@pytest.fixture
def _no_postgres(monkeypatch):
    """Refuse any psycopg connect during bootstrap — the loop must stay off."""
    from atman.skills import postgres_store as _ps

    def _explode(*_a, **_kw):
        raise AssertionError(
            "skills disabled path must not open a PostgreSQL connection"
        )

    monkeypatch.setattr(_ps, "PostgresSkillStore", _explode)
    return _explode


# ── env-var override ──────────────────────────────────────────────────────


def test_env_var_disables_skill_loop(tmp_path: Path, monkeypatch, _no_postgres) -> None:
    """ATMAN_SKILLS_ENABLED=false short-circuits factory.build_deps()."""
    from atman.adapters.agent.config import AgentConfig
    from atman.adapters.agent.factory import build_deps

    monkeypatch.setenv("ATMAN_SKILLS_ENABLED", "false")

    deps, _sm, _store = build_deps(tmp_path, uuid4(), AgentConfig())
    assert deps.skill_manager is None


@pytest.mark.parametrize("value", ["false", "FALSE", "0", "no", "off", ""])
def test_env_var_falsy_values_disable_loop(tmp_path: Path, monkeypatch, value) -> None:
    from atman.adapters.agent.config import AgentConfig
    from atman.adapters.agent.factory import _skills_enabled, build_deps

    monkeypatch.setenv("ATMAN_SKILLS_ENABLED", value)
    assert _skills_enabled() is False

    deps, _sm, _store = build_deps(tmp_path, uuid4(), AgentConfig())
    assert deps.skill_manager is None


def test_env_var_unset_falls_back_to_settings(monkeypatch) -> None:
    from atman.adapters.agent.factory import _skills_enabled
    from atman.config import settings

    monkeypatch.delenv("ATMAN_SKILLS_ENABLED", raising=False)
    original = settings.skills.enabled
    try:
        settings.skills.enabled = True
        assert _skills_enabled() is True
        settings.skills.enabled = False
        assert _skills_enabled() is False
    finally:
        settings.skills.enabled = original


# ── settings override ─────────────────────────────────────────────────────


def test_settings_override_disables_skill_loop(
    tmp_path: Path, monkeypatch, _no_postgres
) -> None:
    """Setting ``settings.skills.enabled = False`` produces a None skill_manager."""
    from atman.adapters.agent.config import AgentConfig
    from atman.adapters.agent.factory import build_deps
    from atman.config import settings

    monkeypatch.delenv("ATMAN_SKILLS_ENABLED", raising=False)
    original = settings.skills.enabled
    settings.skills.enabled = False
    try:
        deps, _sm, _store = build_deps(tmp_path, uuid4(), AgentConfig())
        assert deps.skill_manager is None
    finally:
        settings.skills.enabled = original


# ── downstream consumers must tolerate None ───────────────────────────────


def test_build_instructions_safe_with_no_skill_manager(
    tmp_path: Path, monkeypatch, _no_postgres
) -> None:
    """build_instructions() must not raise, and must not mention the skill tool."""
    from atman.adapters.agent.config import AgentConfig
    from atman.adapters.agent.factory import build_deps
    from atman.adapters.agent.instructions import build_instructions

    monkeypatch.setenv("ATMAN_SKILLS_ENABLED", "false")

    deps, _sm, _store = build_deps(tmp_path, uuid4(), AgentConfig())
    assert deps.skill_manager is None

    text = build_instructions(deps)
    assert isinstance(text, str) and text
    # The instructions text must not advertise the skill-loop tools when the
    # loop is off — otherwise the agent gets told to call a tool that isn't
    # registered.
    assert "atman_skills_mark_result" not in text
    assert "Постоянно доступные навыки" not in text


def test_micro_reflection_skips_skill_hook_when_disabled(
    tmp_path: Path, monkeypatch, _no_postgres
) -> None:
    """MicroReflectionService.reflect() must not blow up without a skill_manager."""
    from atman.adapters.agent.config import AgentConfig
    from atman.adapters.agent.factory import build_deps

    monkeypatch.setenv("ATMAN_SKILLS_ENABLED", "false")
    agent_id = uuid4()
    deps, _sm, _store = build_deps(tmp_path, agent_id, AgentConfig())

    # No skill_manager on the reflection service either — the constructor was
    # invoked with skill_manager=None upstream.
    assert getattr(deps.micro_reflection, "_skill_manager", None) is None

    # Reflect on a non-existent session; service must return a skipped event,
    # not raise from the skill hook.
    event = deps.micro_reflection.reflect(uuid4(), agent_id=agent_id)
    assert event is not None


def test_micro_reflection_without_agent_id_skips_skill_hook() -> None:
    """Even when a skill_manager is wired, reflect(...) without agent_id must
    refuse to call ``process_session_skills`` — the hook needs an agent scope.
    """
    from atman.core.services.reflection_service import MicroReflectionService

    skill_manager_calls: list[tuple] = []

    class _RecordingSkillManager:
        def process_session_skills(self, agent_id, session_id):  # type: ignore[no-untyped-def]
            skill_manager_calls.append((agent_id, session_id))

    class _SessionRepo:
        def get_session(self, *_a, **_kw):
            return None  # short-circuits reflect() with a skipped event

        def get_key_moments_for_session(self, *_a, **_kw):
            return []

    class _NarrativeRev:
        narrative_repo = None  # never read on this short path

    class _EventStore:
        def save(self, _event):
            return None

    svc = MicroReflectionService(
        session_repo=_SessionRepo(),
        narrative_revision=_NarrativeRev(),
        event_store=_EventStore(),
        skill_manager=_RecordingSkillManager(),
    )

    # No agent_id — hook must not fire even though skill_manager is wired.
    svc.reflect(uuid4(), agent_id=None)
    assert skill_manager_calls == []


# ── skill tools are opt-in (no implicit registration) ─────────────────────


def test_make_skill_tools_returns_empty_list_when_disabled() -> None:
    """``make_skill_tools(None, ...)`` returns ``[]`` so callers can splat the
    list straight into ``Agent(tools=...)`` without guarding on enabled.
    """
    from atman.skills.agent_tools import make_skill_tools

    assert make_skill_tools(None, uuid4(), uuid4()) == []


def test_agent_tools_module_has_no_import_time_side_effects() -> None:
    """The module must not instantiate an Agent (or anything that would
    register the four skill tools globally) at import time. Tools are
    constructed per-session via ``make_skill_tools``.
    """
    import atman.skills.agent_tools as at

    src = Path(at.__file__).read_text(encoding="utf-8")
    assert "Agent(" not in src, (
        "agent_tools.py must not instantiate an Agent at import time — "
        "tools are registered by the runner and only when skills are enabled."
    )


def test_runner_does_not_wire_skill_tools_unconditionally() -> None:
    """The runner currently does not register any skill tool. This guard
    survives until somebody intentionally wires them up — at which point
    the wiring must be gated on ``deps.skill_manager is not None``.
    """
    runner_src = Path(
        Path(__file__).resolve().parents[1] / "src/atman/adapters/agent/runner.py"
    ).read_text(encoding="utf-8")
    # If any atman_skills_* tool is added to the runner's tool tuple in the
    # future, it MUST be conditional on ``deps.skill_manager``. We assert the
    # current shape: no skill tool is registered yet.
    assert "atman_skills_invoke" not in runner_src
    assert "atman_skills_capture" not in runner_src
    assert "atman_skills_list_available" not in runner_src
    assert "atman_skills_mark_result" not in runner_src
