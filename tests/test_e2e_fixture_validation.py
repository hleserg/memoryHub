"""Unit tests for e2e session fixture models and corpus validation (no LLM)."""

from __future__ import annotations

import pytest
from e2e.models import (
    ExpectedSessionOutcome,
    FixtureEventRecord,
    KeyMomentFixtureRecord,
    SessionFixtureDocument,
    SessionFixtureMetadata,
    SessionSkeletonItem,
    fixture_events_to_session_events,
    fixture_moments_to_key_moment_inputs,
    validate_fixture_document,
    weighted_mean_valence,
)
from e2e.validation import skeleton_matches_count, validate_corpus

from atman.core.models.experience import EmotionalDepth


def _moment(
    *,
    val: float,
    intensity: float,
    pq: list[str] | None = None,
    values: list[str] | None = None,
    what: str = "After the user_message event, I felt the stakes rise.",
) -> KeyMomentFixtureRecord:
    return KeyMomentFixtureRecord(
        what_happened=what,
        emotional_valence=val,
        emotional_intensity=intensity,
        depth=EmotionalDepth.MEANINGFUL,
        why_it_matters="It matters for how I show up in technical work.",
        values_touched=values or ["competence"],
        principles_confirmed=[],
        principles_questioned=pq or [],
        what_changed="Slight shift in confidence.",
    )


def test_weighted_mean_valence() -> None:
    m = fixture_moments_to_key_moment_inputs(
        [
            _moment(val=0.5, intensity=0.8, what="A"),
            _moment(val=-0.5, intensity=0.2, what="B"),
        ]
    )
    # (0.5*0.8 + (-0.5)*0.2) / (0.8+0.2) = (0.4 - 0.1) / 1.0 = 0.3
    assert abs(weighted_mean_valence(m) - 0.3) < 1e-9


def test_validate_fixture_document_tone_mismatch() -> None:
    doc = SessionFixtureDocument(
        metadata=SessionFixtureMetadata(
            session_number=1,
            theme="test_theme",
            duration_seconds=1200,
            narrative_arc="Started calm, ended tense.",
        ),
        events=[
            FixtureEventRecord(
                event_type="user_message",
                description="We discussed always_admit_uncertainty as a working rule.",
                metadata={},
            ),
            FixtureEventRecord(
                event_type="agent_response",
                description="I admitted I was unsure about the edge case.",
                metadata={},
            ),
            FixtureEventRecord(
                event_type="decision",
                description="We agreed to spike a small prototype first.",
                metadata={},
            ),
        ],
        key_moments=[
            _moment(
                val=0.2,
                intensity=0.5,
                pq=["always_admit_uncertainty"],
                what="After the user_message event, always_admit_uncertainty felt costly.",
            ),
            _moment(val=0.4, intensity=0.5, what="After the decision event, I felt relief."),
        ],
        expected_session_outcome=ExpectedSessionOutcome(
            overall_emotional_tone=0.9,
            key_insight="Mismatch on purpose.",
            alignment_check=True,
        ),
    )
    with pytest.raises(ValueError, match="overall_emotional_tone"):
        validate_fixture_document(doc)


def test_validate_corpus_value_overlap_and_palette() -> None:
    def doc(
        n: int,
        tone: float,
        *,
        pq: list[str] | None = None,
        vals: list[str] | None = None,
        first_event: str | None = None,
    ) -> SessionFixtureDocument:
        v = vals or ["competence"]
        ev0 = first_event or ("User asked about reliability tradeoffs and honesty policy.")
        return SessionFixtureDocument(
            metadata=SessionFixtureMetadata(
                session_number=n,
                theme=f"t{n}",
                duration_seconds=1800,
                narrative_arc=f"arc {n}",
            ),
            events=[
                FixtureEventRecord(
                    event_type="user_message",
                    description=ev0,
                    metadata={},
                ),
                FixtureEventRecord(
                    event_type="agent_response",
                    description="I answered with caveats and a plan.",
                    metadata={},
                ),
                FixtureEventRecord(
                    event_type="decision",
                    description="We chose incremental rollout.",
                    metadata={},
                ),
            ],
            key_moments=[
                _moment(
                    val=tone,
                    intensity=0.5,
                    pq=pq or [],
                    what=f"Key beat {n} tied to earlier user_message.",
                    values=v,
                ),
                _moment(
                    val=tone,
                    intensity=0.5,
                    what=f"Second beat {n} tied to decision.",
                    values=v,
                ),
            ],
            expected_session_outcome=ExpectedSessionOutcome(
                overall_emotional_tone=tone,
                key_insight="Insight",
                alignment_check=True,
            ),
        )

    tones = [0.05, 0.45, 0.1, -0.2, 0.35]
    fixtures = [
        doc(
            1,
            tones[0],
            pq=["always_admit_uncertainty"],
            vals=["competence"],
            first_event=(
                "User asked whether always_admit_uncertainty still applies under delivery pressure."
            ),
        ),
        doc(2, tones[1], pq=[], vals=["competence", "honesty"]),
        doc(3, tones[2], pq=[], vals=["honesty"]),
        doc(4, tones[3], pq=[], vals=["honesty"]),
        doc(5, tones[4], pq=[], vals=["competence"]),
    ]
    # principle questioned in session 1 must appear later — add to session 2 narrative via doc theme?
    # Use session 2 doc with narrative containing phrase - actually _principle_addressee_in_later checks blob
    fixtures[1] = SessionFixtureDocument(
        metadata=SessionFixtureMetadata(
            session_number=2,
            theme="t2",
            duration_seconds=1800,
            narrative_arc="Revisited always_admit_uncertainty and reframed it.",
        ),
        events=fixtures[1].events,
        key_moments=fixtures[1].key_moments,
        expected_session_outcome=fixtures[1].expected_session_outcome,
    )
    for f in fixtures:
        validate_fixture_document(f)
    validate_corpus(fixtures, 5)


def test_skeleton_matches_count() -> None:
    rows = [
        SessionSkeletonItem(
            session_number=1,
            theme="a",
            narrative_arc="x",
            key_values=["v"],
        ),
        SessionSkeletonItem(
            session_number=2,
            theme="b",
            narrative_arc="y",
            key_values=["v"],
        ),
    ]
    skeleton_matches_count(rows, 2)
    with pytest.raises(ValueError):
        skeleton_matches_count(rows, 3)


def test_fixture_events_roundtrip_session_event() -> None:
    from uuid import uuid4

    sid = uuid4()
    evs = fixture_events_to_session_events(
        [
            FixtureEventRecord(
                event_type="user_message",
                description="Hello",
                metadata={"k": 1},
            )
        ],
        sid,
    )
    assert evs[0].session_id == sid
    assert evs[0].metadata["k"] == "1"
