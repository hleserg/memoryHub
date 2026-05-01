"""Smoke tests for Rich terminal helpers (high coverage for presentation layer)."""

from __future__ import annotations

import io
from uuid import uuid4

import pytest
from rich.console import Console

from atman.core.models import (
    EmotionalDepth,
    ExperienceRecord,
    FactRecord,
    FeltSense,
    KeyMoment,
    ReframingNote,
    Relation,
    SessionExperience,
)


@pytest.fixture
def term_console(monkeypatch: pytest.MonkeyPatch) -> io.StringIO:
    import atman.term as term

    buf = io.StringIO()
    fake = Console(
        file=buf,
        width=100,
        theme=term._THEME,
        color_system="truecolor",
        force_terminal=False,
    )
    monkeypatch.setattr(term, "console", fake)
    monkeypatch.setattr(term, "console_err", fake)
    return buf


def test_print_banner_and_messages(term_console: io.StringIO) -> None:
    from atman.term import (
        print_banner,
        print_err,
        print_help_text,
        print_info,
        print_ok,
        print_section,
        print_warn,
    )

    print_banner("Title", "Subtitle")
    print_banner("Only title")
    print_section("Section")
    print_ok("done")
    print_err("oops")
    print_warn("careful")
    print_info("plain")
    print_help_text("Use: add <x> — no markup")
    out = term_console.getvalue()
    assert "Title" in out
    assert "Section" in out
    assert "done" in out
    assert "oops" in out
    assert "add <x>" in out


def test_print_fact_variants(term_console: io.StringIO) -> None:
    from atman.term import print_fact

    other = uuid4()
    fact = FactRecord(
        content="Hello",
        source="src",
        tags=["a", "b"],
        relations=[Relation(target_id=other, relation_type="related_to")],
        metadata={"k": 1},
    )
    print_fact(fact)
    print_fact(FactRecord(content="No extras", source="s"), prefix="  ")
    out = term_console.getvalue()
    assert "Hello" in out
    assert "related_to" in out
    assert "k" in out
    assert "No extras" in out


def test_print_experience_record_full(term_console: io.StringIO) -> None:
    from atman.term import print_experience_record

    felt = FeltSense(
        emotional_valence=0.1,
        emotional_intensity=0.5,
        depth=EmotionalDepth.SURFACE,
    )
    moment = KeyMoment(
        what_happened="Event",
        how_i_felt=felt,
        why_it_matters="Because",
        values_touched=["v1"],
        principles_confirmed=["p1"],
        principles_questioned=["q1"],
        what_changed="c1",
    )
    session = SessionExperience(
        session_id=uuid4(),
        key_moments=[moment],
    )
    session.add_reframing_note(
        ReframingNote(
            reflection="Rethought",
            reflection_type="growth",
            triggered_by="chat",
        )
    )
    record = ExperienceRecord(experience=session)
    print_experience_record(record)
    print_experience_record(record, prefix="  ")
    out = term_console.getvalue()
    assert "Event" in out
    assert "Rethought" in out


def test_print_salience_table(term_console: io.StringIO) -> None:
    from atman.term import print_salience_table

    print_salience_table([(0, 1.0), (7, 0.5)], title="Decay")
    assert "Decay" in term_console.getvalue()
    assert "0.5000" in term_console.getvalue()
