"""HLE-40 — SkillRevisionService tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from atman.skills.in_memory_store import InMemorySkillStore
from atman.skills.manifest import SkillManifest, parse_skill_md, write_skill_md
from atman.skills.models import Skill, SkillKind, SkillOrigin, SkillStatus
from atman.skills.revision import (
    NoopSkillReviser,
    SkillRevisionProposal,
    SkillRevisionService,
    _bump_minor_version,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _make_skill_on_disk(
    tmp_path: Path,
    agent_id: UUID,
    name: str,
    *,
    revision_needed: bool = True,
    revision_priority: int = 2,
    version: str = "0.1.0",
    invocations_count: int = 4,
    failure_count: int = 3,
    body: str = "Original instructions.",
) -> Skill:
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "SKILL.md"
    write_skill_md(
        SkillManifest(
            name=name,
            description=f"{name} description",
            version=version,
            body=body,
        ),
        manifest_path,
    )
    now = _now()
    return Skill(
        id=uuid4(),
        agent_id=agent_id,
        entity_id=uuid4(),
        name=name,
        description=f"{name} description",
        version=version,
        kind=SkillKind.active,
        status=SkillStatus.active,
        origin=SkillOrigin.in_session,
        core=False,
        session_scoped=False,
        user_pinned=False,
        auto_pinned=False,
        invocations_count=invocations_count,
        success_count=max(0, invocations_count - failure_count),
        failure_count=failure_count,
        last_used_at=None,
        sessions_since_use=8,
        revision_needed=revision_needed,
        revision_priority=revision_priority,
        last_revised_at=None,
        manifest_inferred=False,
        skill_root=root,
        manifest_path=manifest_path,
        created_at=now,
        updated_at=now,
    )


class _StubReviser:
    def __init__(self, new_body: str | None = "Revised instructions.", rationale: str = "ok"):
        self._new_body = new_body
        self._rationale = rationale
        self.calls: list[tuple] = []

    def propose_revision(self, skill, manifest_body, failure_summary):
        self.calls.append((skill.name, manifest_body, failure_summary))
        return SkillRevisionProposal(
            new_body=self._new_body,
            new_description=None,
            rationale=self._rationale,
        )


# ── happy path ────────────────────────────────────────────────────────────


def test_revise_pending_applies_proposal_and_bumps_version(tmp_path: Path) -> None:
    store = InMemorySkillStore()
    agent_id = uuid4()
    skill = _make_skill_on_disk(tmp_path, agent_id, "demo", version="0.3.4")
    store.save_skill(skill)
    reviser = _StubReviser(new_body="Better instructions now.", rationale="fixed it")
    service = SkillRevisionService(store=store, reviser=reviser)

    outcomes = service.revise_pending(agent_id)

    assert len(outcomes) == 1
    assert outcomes[0].revised is True
    assert outcomes[0].skill_name == "demo"
    assert outcomes[0].new_version == "0.4.0"
    assert outcomes[0].rationale == "fixed it"

    # Manifest rewritten
    manifest = parse_skill_md(skill.manifest_path)
    assert "Better instructions now." in manifest.body
    assert manifest.version == "0.4.0"

    # Backup file exists alongside the SKILL.md
    backups = list(skill.skill_root.glob("SKILL.md.bak.*"))
    assert len(backups) == 1
    assert outcomes[0].backup_path is not None
    assert outcomes[0].backup_path.exists()

    # Store row updated
    updated = store.get_skill_by_id(skill.id)
    assert updated is not None
    assert updated.revision_needed is False
    assert updated.revision_priority == 0
    assert updated.version == "0.4.0"
    assert updated.last_revised_at is not None

    # Reviser received the manifest body + failure summary
    name, body, summary = reviser.calls[0]
    assert name == "demo"
    assert "Original instructions." in body
    assert "demo" in summary and "rate=" in summary


def test_revise_pending_orders_by_priority(tmp_path: Path) -> None:
    store = InMemorySkillStore()
    agent_id = uuid4()
    low = _make_skill_on_disk(tmp_path, agent_id, "low-prio", revision_priority=1)
    high = _make_skill_on_disk(tmp_path, agent_id, "high-prio", revision_priority=5)
    mid = _make_skill_on_disk(tmp_path, agent_id, "mid-prio", revision_priority=3)
    for s in (low, high, mid):
        store.save_skill(s)

    service = SkillRevisionService(store=store, reviser=_StubReviser())
    outcomes = service.revise_pending(agent_id, max_skills=2)
    assert [o.skill_name for o in outcomes] == ["high-prio", "mid-prio"]
    assert all(o.revised for o in outcomes)


def test_revise_pending_dry_run_does_not_touch_disk_or_store(tmp_path: Path) -> None:
    store = InMemorySkillStore()
    agent_id = uuid4()
    skill = _make_skill_on_disk(tmp_path, agent_id, "demo")
    store.save_skill(skill)
    service = SkillRevisionService(store=store, reviser=_StubReviser())

    outcomes = service.revise_pending(agent_id, dry_run=True)

    assert len(outcomes) == 1
    assert outcomes[0].revised is False  # dry-run never marks as revised
    assert outcomes[0].new_version == "0.2.0"
    assert outcomes[0].backup_path is None

    # Disk untouched
    assert parse_skill_md(skill.manifest_path).body == "Original instructions."
    assert not list(skill.skill_root.glob("SKILL.md.bak.*"))

    # Store row untouched
    after = store.get_skill_by_id(skill.id)
    assert after is not None
    assert after.revision_needed is True
    assert after.version == skill.version


def test_revise_pending_skips_when_proposal_empty(tmp_path: Path) -> None:
    """Reviser returns no body → record outcome but don't write anything."""
    store = InMemorySkillStore()
    agent_id = uuid4()
    skill = _make_skill_on_disk(tmp_path, agent_id, "demo")
    store.save_skill(skill)
    reviser = _StubReviser(new_body=None, rationale="nothing to do")
    service = SkillRevisionService(store=store, reviser=reviser)

    outcomes = service.revise_pending(agent_id)

    assert outcomes[0].revised is False
    assert outcomes[0].rationale == "nothing to do"
    # No backup file created
    assert not list(skill.skill_root.glob("SKILL.md.bak.*"))

    # Store row remains revision_needed=True so the next run can retry
    after = store.get_skill_by_id(skill.id)
    assert after is not None
    assert after.revision_needed is True


def test_revise_pending_whitespace_body_treated_as_decline(tmp_path: Path) -> None:
    store = InMemorySkillStore()
    agent_id = uuid4()
    skill = _make_skill_on_disk(tmp_path, agent_id, "demo")
    store.save_skill(skill)
    reviser = _StubReviser(new_body="   \n  \t ", rationale="empty draft")
    service = SkillRevisionService(store=store, reviser=reviser)

    outcomes = service.revise_pending(agent_id)
    assert outcomes[0].revised is False
    after = store.get_skill_by_id(skill.id)
    assert after is not None
    assert after.revision_needed is True


def test_revise_pending_reviser_error_recorded(tmp_path: Path) -> None:
    store = InMemorySkillStore()
    agent_id = uuid4()
    skill = _make_skill_on_disk(tmp_path, agent_id, "demo")
    store.save_skill(skill)

    class _Boom:
        def propose_revision(self, *_a, **_kw):
            raise RuntimeError("LLM unreachable")

    service = SkillRevisionService(store=store, reviser=_Boom())
    outcomes = service.revise_pending(agent_id)
    assert outcomes[0].revised is False
    assert "error" in outcomes[0].rationale
    # Skill still flagged for revision so we'll try again next cycle
    after = store.get_skill_by_id(skill.id)
    assert after is not None
    assert after.revision_needed is True


def test_revise_pending_noop_returns_skip(tmp_path: Path) -> None:
    store = InMemorySkillStore()
    agent_id = uuid4()
    skill = _make_skill_on_disk(tmp_path, agent_id, "demo")
    store.save_skill(skill)
    service = SkillRevisionService(store=store, reviser=NoopSkillReviser())

    outcomes = service.revise_pending(agent_id)
    assert len(outcomes) == 1
    assert outcomes[0].revised is False
    after = store.get_skill_by_id(skill.id)
    assert after is not None
    assert after.revision_needed is True


def test_revise_pending_rejects_invalid_max(tmp_path: Path) -> None:
    service = SkillRevisionService(store=InMemorySkillStore(), reviser=NoopSkillReviser())
    with pytest.raises(ValueError, match="must be positive"):
        service.revise_pending(uuid4(), max_skills=0)


def test_revise_pending_no_candidates(tmp_path: Path) -> None:
    service = SkillRevisionService(store=InMemorySkillStore(), reviser=_StubReviser())
    assert service.revise_pending(uuid4()) == []


def test_description_override_applied(tmp_path: Path) -> None:
    store = InMemorySkillStore()
    agent_id = uuid4()
    skill = _make_skill_on_disk(tmp_path, agent_id, "demo")
    store.save_skill(skill)

    class _RewritesDescription:
        def propose_revision(self, skill, manifest_body, failure_summary):
            return SkillRevisionProposal(
                new_body="new body",
                new_description="A sharper description.",
                rationale="x",
            )

    service = SkillRevisionService(store=store, reviser=_RewritesDescription())
    outcomes = service.revise_pending(agent_id)
    assert outcomes[0].revised is True

    after = store.get_skill_by_id(skill.id)
    assert after is not None
    assert after.description == "A sharper description."


# ── helpers ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "version,expected",
    [
        ("0.1.0", "0.2.0"),
        ("1.5.7", "1.6.0"),
        ("2.0", "2.1.0"),
        ("3", "3.1.0"),
        ("not-a-version", "not-a-version+rev1"),
    ],
)
def test_bump_minor_version(version: str, expected: str) -> None:
    assert _bump_minor_version(version) == expected
