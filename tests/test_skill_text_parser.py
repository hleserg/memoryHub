"""Tests for InvocationTextParser — HLE-37 fallback for weak tool-use models."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from atman.skills.in_memory_store import InMemorySkillStore
from atman.skills.models import Skill, SkillKind, SkillOrigin, SkillStatus
from atman.skills.text_parser import (
    DEFAULT_MIN_CONFIDENCE,
    InferredInvocation,
    InvocationTextParser,
    SCORE_EXACT_NAME,
    SCORE_KEYWORD_MULTI,
    SCORE_KEYWORD_SINGLE,
    SCORE_NAME_VARIANT,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _make_skill_with_manifest(
    tmp_path: Path,
    agent_id,
    name: str,
    keywords: list[str],
    status: SkillStatus = SkillStatus.active,
) -> Skill:
    from atman.skills.manifest import SkillManifest, write_skill_md

    skill_root = tmp_path / name
    skill_root.mkdir()
    manifest_path = skill_root / "SKILL.md"

    manifest = SkillManifest(
        name=name,
        description=f"Does {name}.",
        triggers_keywords=keywords,
        min_confidence=0.65,
    )
    write_skill_md(manifest, manifest_path)

    now = _now()
    return Skill(
        id=uuid4(),
        agent_id=agent_id,
        entity_id=uuid4(),
        name=name,
        description=f"Does {name}.",
        version="0.1.0",
        kind=SkillKind.active,
        status=status,
        origin=SkillOrigin.in_session,
        core=False,
        session_scoped=False,
        user_pinned=False,
        auto_pinned=False,
        invocations_count=0,
        success_count=0,
        failure_count=0,
        last_used_at=None,
        sessions_since_use=0,
        revision_needed=False,
        revision_priority=0,
        last_revised_at=None,
        manifest_inferred=False,
        skill_root=skill_root,
        manifest_path=manifest_path,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def agent_id():
    return uuid4()


@pytest.fixture
def session_id():
    return uuid4()


# ── parse() — pure detection ──────────────────────────────────────────────


class TestParse:
    def test_exact_kebab_name_is_strongest_match(self, tmp_path, agent_id, session_id):
        store = InMemorySkillStore()
        skill = _make_skill_with_manifest(tmp_path, agent_id, "outlet-control", ["bulb"])
        store.save_skill(skill)
        parser = InvocationTextParser(store=store)

        text = "I will use outlet-control to handle the lamp."
        inferred = parser.parse(text, agent_id, session_id)

        assert len(inferred) == 1
        assert inferred[0].skill_name == "outlet-control"
        assert inferred[0].confidence == SCORE_EXACT_NAME
        assert "outlet-control" in inferred[0].matched_text
        assert "exact skill name" in inferred[0].reason

    def test_underscore_variant_match(self, tmp_path, agent_id, session_id):
        store = InMemorySkillStore()
        skill = _make_skill_with_manifest(tmp_path, agent_id, "outlet-control", [])
        store.save_skill(skill)
        parser = InvocationTextParser(store=store)

        text = "calling outlet_control with the new args"
        inferred = parser.parse(text, agent_id, session_id)

        assert len(inferred) == 1
        assert inferred[0].confidence == SCORE_NAME_VARIANT
        assert "outlet_control" in inferred[0].reason

    def test_space_variant_match(self, tmp_path, agent_id, session_id):
        store = InMemorySkillStore()
        skill = _make_skill_with_manifest(tmp_path, agent_id, "outlet-control", [])
        store.save_skill(skill)
        parser = InvocationTextParser(store=store)

        inferred = parser.parse(
            "I'll engage outlet control for the next room.", agent_id, session_id
        )
        assert len(inferred) == 1
        assert inferred[0].confidence == SCORE_NAME_VARIANT

    def test_single_keyword_match(self, tmp_path, agent_id, session_id):
        store = InMemorySkillStore()
        skill = _make_skill_with_manifest(
            tmp_path, agent_id, "weather-fetcher", ["forecast"]
        )
        store.save_skill(skill)
        parser = InvocationTextParser(store=store)

        inferred = parser.parse("Let me grab the forecast for tomorrow.", agent_id, session_id)
        assert len(inferred) == 1
        assert inferred[0].confidence == SCORE_KEYWORD_SINGLE
        assert "'forecast'" in inferred[0].reason

    def test_multiple_keywords_boost_confidence(self, tmp_path, agent_id, session_id):
        store = InMemorySkillStore()
        skill = _make_skill_with_manifest(
            tmp_path, agent_id, "weather-fetcher", ["forecast", "temperature", "wind"]
        )
        store.save_skill(skill)
        parser = InvocationTextParser(store=store)

        text = "The forecast says high temperature today with light wind."
        inferred = parser.parse(text, agent_id, session_id)

        assert len(inferred) == 1
        assert inferred[0].confidence == SCORE_KEYWORD_MULTI
        assert "3 trigger keywords" in inferred[0].reason

    def test_word_boundary_prevents_overmatch(self, tmp_path, agent_id, session_id):
        """Skill name 'map' must not match inside 'mapping'."""
        store = InMemorySkillStore()
        skill = _make_skill_with_manifest(tmp_path, agent_id, "map", [])
        store.save_skill(skill)
        parser = InvocationTextParser(store=store)

        assert parser.parse("the mapping is incorrect", agent_id, session_id) == []
        # Standalone 'map' still matches:
        result = parser.parse("update the map for the user", agent_id, session_id)
        assert len(result) == 1

    def test_below_threshold_filtered_out(self, tmp_path, agent_id, session_id):
        store = InMemorySkillStore()
        skill = _make_skill_with_manifest(
            tmp_path, agent_id, "weather-fetcher", ["forecast"]
        )
        store.save_skill(skill)
        parser = InvocationTextParser(store=store, min_confidence=0.9)

        # SCORE_KEYWORD_SINGLE = 0.75 < 0.9 → filtered out
        assert parser.parse("Let me grab the forecast.", agent_id, session_id) == []

    def test_inactive_skills_ignored(self, tmp_path, agent_id, session_id):
        store = InMemorySkillStore()
        draft = _make_skill_with_manifest(
            tmp_path, agent_id, "draft-skill", [], status=SkillStatus.draft
        )
        store.save_skill(draft)
        parser = InvocationTextParser(store=store)

        assert parser.parse("calling draft-skill now", agent_id, session_id) == []

    def test_empty_text_returns_empty(self, tmp_path, agent_id, session_id):
        store = InMemorySkillStore()
        store.save_skill(_make_skill_with_manifest(tmp_path, agent_id, "any-skill", ["x"]))
        parser = InvocationTextParser(store=store)

        assert parser.parse("", agent_id, session_id) == []
        assert parser.parse("   \n  ", agent_id, session_id) == []

    def test_empty_store_returns_empty(self, agent_id, session_id):
        parser = InvocationTextParser(store=InMemorySkillStore())
        assert parser.parse("any text", agent_id, session_id) == []

    def test_dedup_per_skill_keeps_highest_confidence(self, tmp_path, agent_id, session_id):
        """If both name match (1.0) and keyword (0.9) hit, keep the name match."""
        store = InMemorySkillStore()
        skill = _make_skill_with_manifest(
            tmp_path, agent_id, "outlet-control", ["outlet"]
        )
        store.save_skill(skill)
        parser = InvocationTextParser(store=store)

        text = "Using outlet-control to switch the outlet."
        inferred = parser.parse(text, agent_id, session_id)
        assert len(inferred) == 1
        assert inferred[0].confidence == SCORE_EXACT_NAME

    def test_results_sorted_by_confidence_desc(self, tmp_path, agent_id, session_id):
        store = InMemorySkillStore()
        store.save_skill(_make_skill_with_manifest(tmp_path, agent_id, "a-skill", ["alpha"]))
        store.save_skill(_make_skill_with_manifest(tmp_path, agent_id, "b-skill", []))
        parser = InvocationTextParser(store=store)

        text = "running b-skill after checking alpha"
        inferred = parser.parse(text, agent_id, session_id)
        assert len(inferred) == 2
        assert inferred[0].skill_name == "b-skill"  # exact name match, 1.0
        assert inferred[1].skill_name == "a-skill"  # keyword match, 0.75

    def test_max_per_call_caps_results(self, tmp_path, agent_id, session_id):
        store = InMemorySkillStore()
        for i in range(10):
            store.save_skill(
                _make_skill_with_manifest(tmp_path, agent_id, f"skill-{i}", [f"kw{i}"])
            )
        parser = InvocationTextParser(store=store, max_per_call=3)

        text = " ".join(f"kw{i}" for i in range(10))
        inferred = parser.parse(text, agent_id, session_id)
        assert len(inferred) == 3

    def test_invalid_min_confidence_raises(self):
        store = InMemorySkillStore()
        with pytest.raises(ValueError, match=r"min_confidence must be in \[0, 1\]"):
            InvocationTextParser(store=store, min_confidence=1.5)
        with pytest.raises(ValueError, match=r"min_confidence must be in \[0, 1\]"):
            InvocationTextParser(store=store, min_confidence=-0.1)


# ── parse_and_record() — store side effects ──────────────────────────────


class TestParseAndRecord:
    def test_creates_invocation_with_unclear_marker(
        self, tmp_path, agent_id, session_id
    ):
        store = InMemorySkillStore()
        skill = _make_skill_with_manifest(tmp_path, agent_id, "outlet-control", [])
        store.save_skill(skill)
        parser = InvocationTextParser(store=store)

        ids = parser.parse_and_record("calling outlet-control now", agent_id, session_id)

        assert len(ids) == 1
        invocation = store._invocations[ids[0]]
        assert invocation.skill_id == skill.id
        assert invocation.session_id == session_id
        assert invocation.agent_marker == "unclear"
        assert invocation.input_context_summary is not None
        assert invocation.input_context_summary.startswith("inferred_from_text:")
        assert invocation.agent_marker_note is not None
        assert "auto-inferred" in invocation.agent_marker_note

    def test_no_match_creates_nothing(self, tmp_path, agent_id, session_id):
        store = InMemorySkillStore()
        skill = _make_skill_with_manifest(tmp_path, agent_id, "outlet-control", [])
        store.save_skill(skill)
        parser = InvocationTextParser(store=store)

        assert parser.parse_and_record("unrelated text", agent_id, session_id) == []
        # The skill must not have any invocations either:
        invocations = store.get_unprocessed_invocations(agent_id, session_id)
        assert invocations == []

    def test_store_failure_logged_but_does_not_abort_batch(
        self, tmp_path, agent_id, session_id
    ):
        """One bad create_invocation must not stop the rest of the batch."""
        from atman.skills.manifest import SkillManifest, write_skill_md

        # Two skills mentioned in text
        good = _make_skill_with_manifest(tmp_path, agent_id, "good-skill", [])
        manifest = SkillManifest(name="bad-skill", description="bad")
        bad_root = tmp_path / "bad-skill"
        bad_root.mkdir()
        write_skill_md(manifest, bad_root / "SKILL.md")
        bad = _make_skill_with_manifest(tmp_path, agent_id, "another-good", [])

        store = InMemorySkillStore()
        store.save_skill(good)
        store.save_skill(bad)

        # Wrap store.create_invocation: raise on the FIRST call only
        call_count = {"n": 0}
        original = store.create_invocation

        def flaky(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("simulated DB hiccup")
            return original(*args, **kwargs)

        store.create_invocation = flaky  # type: ignore[method-assign]
        parser = InvocationTextParser(store=store)

        text = "using good-skill and another-good in this turn"
        ids = parser.parse_and_record(text, agent_id, session_id)
        # First create_invocation raised, second succeeded → exactly one id
        assert len(ids) == 1


# ── helpers ───────────────────────────────────────────────────────────────


def test_default_min_confidence_matches_expectations():
    assert 0.6 <= DEFAULT_MIN_CONFIDENCE <= 0.85


def test_inferred_invocation_is_frozen():
    inv = InferredInvocation(
        skill_id=uuid4(),
        skill_name="x",
        confidence=0.9,
        matched_text="x",
        reason="r",
    )
    with pytest.raises(Exception):
        inv.confidence = 0.0  # type: ignore[misc]
