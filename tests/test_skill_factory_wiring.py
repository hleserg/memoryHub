"""Tests for skill-loop wiring fixes from PR #572 follow-up.

These tests pin down the regressions surfaced by Devin Review on PR #572:

1. ``build_deps`` must construct ``MicroReflectionService`` AFTER
   ``skill_manager`` so the reflection hook actually fires (was dead code).
2. ``build_deps`` must fall back to ``InMemorySkillStore`` when PostgreSQL is
   unreachable so the no-external-service local path keeps working.
3. ``PostgresSkillStore`` must reject cross-agent access (RLS sanity check at
   the Python level — the SQL-level enforcement also runs but cannot be tested
   without a live DB).
4. The migration must persist a ``description`` column so skill descriptions
   survive a PostgreSQL roundtrip.
5. ``skills/cli.py`` must use Rich via ``atman.term`` instead of raw ``print``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

# ── BUG #1 — factory wires skill_manager into micro reflection ────────────


def test_build_deps_passes_skill_manager_to_micro_reflection(tmp_path: Path) -> None:
    """The MicroReflectionService inside AtmanDeps must receive the same
    skill_manager that AtmanDeps does — otherwise the skill-loop hook is
    dead code.
    """
    from atman.adapters.agent.config import AgentConfig
    from atman.adapters.agent.factory import build_deps

    agent_id = uuid4()
    deps, _sm, _store = build_deps(tmp_path, agent_id, AgentConfig())

    # MicroReflectionService stores the skill_manager on a private attribute;
    # we assert the wiring on identity to catch even subtle reordering bugs.
    micro = deps.micro_reflection
    assert deps.skill_manager is not None, (
        "skill_manager should be auto-wired (PostgreSQL fallback to "
        "InMemorySkillStore covers no-DB local dev)"
    )
    assert getattr(micro, "_skill_manager", None) is deps.skill_manager, (
        "build_deps must pass skill_manager= to MicroReflectionService; see PR #572 Devin review."
    )


def test_runner_passes_agent_id_to_micro_reflection_reflect() -> None:
    """``deps.micro_reflection.reflect(session_id)`` must propagate
    ``agent_id`` so the skill-loop hook actually fires.

    This is a source-level guard against the Devin Review finding that
    runner.py forgot the ``agent_id=`` kwarg.
    """
    runner_path = Path(__file__).resolve().parents[1] / "src/atman/adapters/agent/runner.py"
    body = runner_path.read_text(encoding="utf-8")
    # The exact call site we care about
    assert "deps.micro_reflection.reflect(session_id, agent_id=deps.agent_id)" in body, (
        "runner.py must call deps.micro_reflection.reflect(..., "
        "agent_id=deps.agent_id) so the skill-loop hook fires."
    )


def test_runner_writes_skills_marker_even_when_finish_session_raises() -> None:
    """``write_session_skills_marker`` must run regardless of finish_session
    outcome — the invocation data it summarises is already persisted before
    finalize runs, so a finalize failure (DB error, unexpected ValueError,
    …) must not cost us the marker.

    Source-level guard for Devin Review BUG_..._7c1b66... .
    """
    runner_path = Path(__file__).resolve().parents[1] / "src/atman/adapters/agent/runner.py"
    body = runner_path.read_text(encoding="utf-8")
    # The marker write must happen via the deferred-exception pattern,
    # not directly inside the try/except for finish_session.
    assert "deferred_finish_exc" in body, (
        "runner.py must defer the finish_session exception until after the "
        "session-skills marker has been attempted."
    )
    # Verify the structural ordering: marker call → re-raise of deferred exc.
    marker_idx = body.find("write_session_skills_marker(")
    raise_idx = body.find("raise deferred_finish_exc")
    assert marker_idx != -1, "runner.py must call write_session_skills_marker"
    assert raise_idx != -1, "runner.py must re-raise the deferred finish exception"
    assert marker_idx < raise_idx, (
        "write_session_skills_marker must be invoked BEFORE re-raising the "
        "deferred finish_session exception."
    )


# ── WARNING #6 — InMemorySkillStore fallback when PostgreSQL is down ─────


def test_build_deps_falls_back_to_in_memory_skill_store_when_postgres_unavailable(
    tmp_path: Path,
) -> None:
    """Per AGENTS.md the project must run with no external services. When
    PostgreSQL is unreachable, skill-loop must degrade to InMemorySkillStore,
    not crash and not return ``skill_manager=None``.
    """
    from atman.adapters.agent.config import AgentConfig
    from atman.adapters.agent.factory import build_deps
    from atman.skills.in_memory_store import InMemorySkillStore

    agent_id = uuid4()

    def _explode(*_args, **_kwargs):
        raise ConnectionError("simulated: no postgres in this env")

    with patch("atman.skills.postgres_store.PostgresSkillStore", side_effect=_explode):
        deps, _sm, _store = build_deps(tmp_path, agent_id, AgentConfig())

    assert deps.skill_manager is not None, "fallback must not silently disable the loop"
    inner_store = getattr(deps.skill_manager, "_store", None)
    assert isinstance(inner_store, InMemorySkillStore), (
        "PostgreSQL failure must fall back to InMemorySkillStore "
        f"(got {type(inner_store).__name__})"
    )


def test_build_deps_disables_skill_loop_when_setting_is_off(tmp_path: Path) -> None:
    """When ``settings.skills.enabled = False`` skill-loop must stay off."""
    from atman.adapters.agent.config import AgentConfig
    from atman.adapters.agent.factory import build_deps
    from atman.config import settings

    agent_id = uuid4()
    original = settings.skills.enabled
    settings.skills.enabled = False
    try:
        deps, _sm, _store = build_deps(tmp_path, agent_id, AgentConfig())
        assert deps.skill_manager is None
    finally:
        settings.skills.enabled = original


# ── BUG #2 — PostgresSkillStore agent binding (cross-agent rejection) ─────


def test_postgres_skill_store_rejects_cross_agent_access() -> None:
    """The store binds to one agent at construction; queries that pass a
    different agent_id must raise — this is the Python-level part of the RLS
    safety net.
    """
    from atman.skills.postgres_store import PostgresSkillStore

    bound = uuid4()
    other = uuid4()
    store = PostgresSkillStore(db_url="postgresql://stub", agent_id=bound)

    with pytest.raises(ValueError, match="bound to agent"):
        # use a non-existent method-friendly path that exercises _agent_for
        # without opening a real connection
        store._agent_for(other)

    # bound agent passes through
    assert store._agent_for(bound) == bound
    # None resolves to the bound agent
    assert store._agent_for(None) == bound


def test_postgres_skill_store_requires_bound_agent_for_skill_id_ops() -> None:
    """Skill-id-only methods must refuse to run when no agent is bound.

    Using a raw connection without setting ``atman.current_agent`` would
    silently drop rows under FORCE ROW LEVEL SECURITY.
    """
    from atman.skills.postgres_store import PostgresSkillStore

    store = PostgresSkillStore(db_url="postgresql://stub", agent_id=None)

    with pytest.raises(RuntimeError, match="bound to an agent"):
        store._resolve_agent_for_skill(uuid4())


def test_postgres_skill_store_routes_every_write_through_conn() -> None:
    """All write methods must route through ``_conn`` (which sets the RLS
    session variable). A raw ``psycopg.connect`` call without
    ``set_config('atman.current_agent', …)`` would silently no-op under
    FORCE ROW LEVEL SECURITY.

    This is a source-level audit: it scans postgres_store.py to make sure no
    method uses ``psycopg.connect`` directly anymore.
    """
    store_path = Path(__file__).resolve().parents[1] / "src/atman/skills/postgres_store.py"
    body = store_path.read_text(encoding="utf-8")

    # Only one place is allowed to call psycopg.connect directly: _conn itself.
    raw_connects = body.count("psycopg.connect(")
    assert raw_connects == 1, (
        f"postgres_store.py must call psycopg.connect ONCE (inside _conn). "
        f"Found {raw_connects} occurrences — likely an RLS bypass regression."
    )


# ── BUG #3 — migration persists Skill.description ─────────────────────────


def test_skills_migration_persists_description_column() -> None:
    """The 0015 migration must have a description column so
    Skill.description round-trips correctly through PostgreSQL.

    Without it, ``_row_to_skill`` always returns ``""`` and bootstrap
    injection / agent tools silently lose their human-readable summaries.
    """
    migration = Path(__file__).resolve().parents[1] / "migrations/versions/0015_skills.sql"
    sql = migration.read_text(encoding="utf-8")
    assert "description" in sql.lower(), "missing description column in 0015_skills.sql"
    # the column must be inside the skills table definition
    skills_block = sql.split("CREATE TABLE IF NOT EXISTS public.skills")[1].split(");")[0]
    assert "description" in skills_block.lower(), (
        "description column must be on public.skills (not just mentioned in a comment)"
    )


def test_postgres_skill_store_save_includes_description() -> None:
    """Source-level check that save_skill INSERTs/UPDATEs description.

    A live DB test would catch this too, but we want a deterministic guard
    that runs in CI without external services.
    """
    store_path = Path(__file__).resolve().parents[1] / "src/atman/skills/postgres_store.py"
    body = store_path.read_text(encoding="utf-8")
    assert "%(description)s" in body, "save_skill must bind description in its INSERT"
    assert "description = EXCLUDED.description" in body, (
        "ON CONFLICT clause must also update description on conflict"
    )


# ── STYLE #5 — Skills CLI uses Rich via atman.term ────────────────────────


def test_skills_cli_uses_rich_not_raw_print() -> None:
    """AGENTS.md mandates Rich for every CLI entrypoint with structured/
    tabular output. Skills CLI was flagged by Devin for using raw print().

    The check tokenises each line and ensures every callsite of ``print``
    (the builtin) is replaced by an ``atman.term`` helper or a Rich
    ``console.print``. Comments and docstrings are ignored.
    """
    import io
    import token
    import tokenize

    cli_path = Path(__file__).resolve().parents[1] / "src/atman/skills/cli.py"
    body = cli_path.read_text(encoding="utf-8")

    raw_print_lines: list[tuple[int, str]] = []
    try:
        tokens = list(tokenize.tokenize(io.BytesIO(body.encode("utf-8")).readline))
    except Exception as exc:  # tokenize raises various error types across versions
        pytest.fail(f"could not tokenize skills/cli.py: {exc}")

    for idx, tok in enumerate(tokens):
        if tok.type != token.NAME or tok.string != "print":
            continue
        # Must be a bare ``print`` (not ``something.print`` or ``print_xxx``).
        prev = tokens[idx - 1] if idx > 0 else None
        if prev is not None and prev.type == token.OP and prev.string == ".":
            continue  # console.print, foo.print, etc.
        # Must be a call: ``print(...)``
        nxt = tokens[idx + 1] if idx + 1 < len(tokens) else None
        if nxt is None or not (nxt.type == token.OP and nxt.string == "("):
            continue
        raw_print_lines.append((tok.start[0], body.splitlines()[tok.start[0] - 1]))

    assert not raw_print_lines, (
        "skills/cli.py must use Rich helpers from atman.term, not raw print(). "
        f"Found raw print at: {raw_print_lines}"
    )

    # Must import from atman.term
    assert "from atman.term import" in body, "skills/cli.py must import from atman.term"


# ── WARNING — pyyaml is a declared dependency ────────────────────────────


def test_pyyaml_is_declared_dependency() -> None:
    """``yaml`` is imported at module top-level in skills/manifest.py; it
    must be a direct dependency, not a transitive one — otherwise
    ``atman-skills show`` crashes for users who don't happen to have a
    transitive provider installed.
    """
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    body = pyproject.read_text(encoding="utf-8")

    # Find the dependencies = [...] block under [project]
    project_block = body.split("[project]", 1)[1].split("[project.optional-dependencies]", 1)[0]
    assert "pyyaml" in project_block.lower(), (
        "pyyaml must be in [project].dependencies — it is imported at module "
        "top-level in src/atman/skills/manifest.py"
    )


def test_micro_reflection_uses_skill_manager_when_both_provided() -> None:
    """End-to-end sanity: with the factory-wired skill_manager and
    agent_id, the reflection hook actually invokes process_session_skills.
    """
    from atman.adapters.storage.in_memory_reflection_store import InMemoryReflectionEventStore
    from atman.core.models import NarrativeDocument
    from atman.core.models.narrative import LayerType, NarrativeLayer
    from atman.core.services.narrative_revision import NarrativeRevisionService
    from atman.core.services.reflection_service import MicroReflectionService

    skill_manager = MagicMock()
    session_repo = MagicMock()
    session_repo.get_session.return_value = MagicMock()
    session_repo.get_key_moments_for_session.return_value = [MagicMock()]

    narrative_revision = MagicMock(spec=NarrativeRevisionService)
    narrative_revision.update_recent_layer.return_value = "ok"
    narrative_revision.narrative_repo = MagicMock()
    narrative_revision.narrative_repo.get_current.return_value = NarrativeDocument(
        identity_id=uuid4(),
        core_layer=NarrativeLayer(content="c", layer_type=LayerType.CORE),
        recent_layer=NarrativeLayer(content="r", layer_type=LayerType.RECENT),
    )

    service = MicroReflectionService(
        session_repo=session_repo,
        narrative_revision=narrative_revision,
        event_store=InMemoryReflectionEventStore(),
        skill_manager=skill_manager,
    )

    fake_exp = MagicMock()
    fake_exp.id = uuid4()
    agent_id = uuid4()
    session_id = uuid4()
    with patch(
        "atman.core.services.reflection_service.build_session_experience",
        return_value=fake_exp,
    ):
        service.reflect(session_id, agent_id=agent_id)

    skill_manager.process_session_skills.assert_called_once_with(agent_id, session_id)
