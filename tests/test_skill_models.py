"""Tests for skill domain models and SKILL.md manifest parsing."""

from __future__ import annotations

import textwrap
from pathlib import Path
from uuid import uuid4

import pytest

from atman.skills.models import (
    Skill,
    SkillInvocation,
    SkillKind,
    SkillOrigin,
    SkillStatus,
    SkillSuggestion,
    SuggestionStrength,
)


def _make_skill(**kwargs) -> Skill:
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    defaults = dict(
        id=uuid4(),
        agent_id=uuid4(),
        entity_id=uuid4(),
        name="test-skill",
        description="Does something useful.\nSecond line.",
        version="0.1.0",
        kind=SkillKind.active,
        status=SkillStatus.active,
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
        skill_root=Path("/tmp/skills/test-skill"),
        manifest_path=Path("/tmp/skills/test-skill/SKILL.md"),
        created_at=now,
        updated_at=now,
    )
    defaults.update(kwargs)
    return Skill(**defaults)  # type: ignore[arg-type]


class TestSkillModel:
    def test_is_pinned_user(self):
        s = _make_skill(user_pinned=True, auto_pinned=False)
        assert s.is_pinned is True

    def test_is_pinned_auto(self):
        s = _make_skill(user_pinned=False, auto_pinned=True)
        assert s.is_pinned is True

    def test_is_pinned_neither(self):
        s = _make_skill(user_pinned=False, auto_pinned=False)
        assert s.is_pinned is False

    def test_description_short_single_line(self):
        s = _make_skill(description="A single line.")
        assert s.description_short == "A single line."

    def test_description_short_multiline(self):
        s = _make_skill(description="First line.\nSecond line.")
        assert s.description_short == "First line."


class TestSkillEnums:
    def test_kind_values(self):
        assert SkillKind.active.value == "active"
        assert SkillKind.passive.value == "passive"

    def test_status_values(self):
        assert SkillStatus.draft.value == "draft"
        assert SkillStatus.active.value == "active"
        assert SkillStatus.disabled.value == "disabled"

    def test_origin_values(self):
        assert SkillOrigin.in_session.value == "in_session"
        assert SkillOrigin.reflection_pattern.value == "reflection_pattern"
        assert SkillOrigin.external.value == "external"


class TestManifestParsing:
    def test_parse_valid_skill_md(self, tmp_path: Path):
        from atman.skills.manifest import parse_skill_md

        content = textwrap.dedent("""\
            ---
            name: smart-outlet
            description: |
              Controls smart outlets.
            metadata:
              version: "0.2.0"
              atman:
                kind: active
                origin: in_session
                triggers:
                  keywords:
                    - розетка
                    - outlet
                  embedding_anchors:
                    - "управление розеткой"
                  min_confidence: 0.7
                dependencies:
                  skills: []
                  python_packages:
                    - requests>=2.31
                runtime:
                  entry: scripts/run.py
                  sandbox: subprocess
            ---

            # Smart Outlet

            Does stuff.
        """)
        p = tmp_path / "SKILL.md"
        p.write_text(content)

        manifest = parse_skill_md(p)
        assert manifest.name == "smart-outlet"
        assert "Controls" in manifest.description
        assert manifest.version == "0.2.0"
        assert manifest.kind == SkillKind.active
        assert manifest.origin == SkillOrigin.in_session
        assert "розетка" in manifest.triggers_keywords
        assert manifest.min_confidence == 0.7
        assert "requests>=2.31" in manifest.dependencies_python_packages
        assert manifest.runtime_entry == "scripts/run.py"
        assert manifest.runtime_sandbox == "subprocess"
        assert "Smart Outlet" in manifest.body

    def test_parse_missing_frontmatter_raises(self, tmp_path: Path):
        from atman.skills.manifest import parse_skill_md

        p = tmp_path / "SKILL.md"
        p.write_text("# No frontmatter here\n")

        with pytest.raises(ValueError, match="No valid YAML frontmatter"):
            parse_skill_md(p)

    def test_parse_missing_name_raises(self, tmp_path: Path):
        from atman.skills.manifest import parse_skill_md

        p = tmp_path / "SKILL.md"
        p.write_text("---\ndescription: no name\n---\n# body\n")

        with pytest.raises(ValueError, match="missing required field"):
            parse_skill_md(p)

    def test_write_then_parse_roundtrip(self, tmp_path: Path):
        from atman.skills.manifest import SkillManifest, parse_skill_md, write_skill_md

        manifest = SkillManifest(
            name="round-trip",
            description="Test roundtrip.",
            version="1.0.0",
            kind=SkillKind.passive,
            origin=SkillOrigin.reflection_pattern,
            triggers_keywords=["foo", "bar"],
            triggers_embedding_anchors=["some anchor text"],
            min_confidence=0.8,
            body="## Instructions\n\nDo stuff.\n",
        )
        p = tmp_path / "SKILL.md"
        write_skill_md(manifest, p)

        parsed = parse_skill_md(p)
        assert parsed.name == "round-trip"
        assert parsed.kind == SkillKind.passive
        assert parsed.origin == SkillOrigin.reflection_pattern
        assert "foo" in parsed.triggers_keywords
        assert parsed.min_confidence == 0.8
        assert "Do stuff." in parsed.body
