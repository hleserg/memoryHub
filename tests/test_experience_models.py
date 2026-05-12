"""
Tests for experience domain models.

Tests cover all invariants from the work package:
- Valid/invalid values for emotional_valence, emotional_intensity, depth
- Immutability of original key moments
- Adding reframing notes (append-only)
- Salience decay calculation
- Access count updates
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from atman.core.models import (
    EmotionalDepth,
    ExperienceRecord,
    FeltSense,
    KeyMoment,
    ReframingNote,
    SessionExperience,
)


class TestFeltSense:
    """Test FeltSense validation."""

    def test_valid_felt_sense(self):
        """Test creating a valid FeltSense."""
        felt = FeltSense(
            emotional_valence=0.5, emotional_intensity=0.7, depth=EmotionalDepth.MEANINGFUL
        )
        assert felt.emotional_valence == 0.5
        assert felt.emotional_intensity == 0.7
        assert felt.depth == EmotionalDepth.MEANINGFUL

    def test_emotional_valence_boundaries(self):
        """Test emotional_valence must be between -1.0 and 1.0."""
        # Valid boundaries
        FeltSense(emotional_valence=-1.0, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE)
        FeltSense(emotional_valence=1.0, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE)

        # Invalid: too low
        with pytest.raises(ValidationError):
            FeltSense(emotional_valence=-1.1, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE)

        # Invalid: too high
        with pytest.raises(ValidationError):
            FeltSense(emotional_valence=1.1, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE)

    def test_emotional_intensity_boundaries(self):
        """Test emotional_intensity must be between 0.0 and 1.0."""
        # Valid boundaries
        FeltSense(emotional_valence=0.0, emotional_intensity=0.0, depth=EmotionalDepth.SURFACE)
        FeltSense(emotional_valence=0.0, emotional_intensity=1.0, depth=EmotionalDepth.SURFACE)

        # Invalid: negative
        with pytest.raises(ValidationError):
            FeltSense(emotional_valence=0.0, emotional_intensity=-0.1, depth=EmotionalDepth.SURFACE)

        # Invalid: too high
        with pytest.raises(ValidationError):
            FeltSense(emotional_valence=0.0, emotional_intensity=1.1, depth=EmotionalDepth.SURFACE)

    def test_depth_enum_values(self):
        """Test depth accepts only valid enum values."""
        for depth in EmotionalDepth:
            felt = FeltSense(emotional_valence=0.0, emotional_intensity=0.5, depth=depth)
            assert felt.depth == depth


class TestKeyMoment:
    """Test KeyMoment model."""

    def test_create_key_moment(self):
        """Test creating a valid KeyMoment."""
        felt = FeltSense(
            emotional_valence=0.3, emotional_intensity=0.6, depth=EmotionalDepth.MEANINGFUL
        )
        moment = KeyMoment(
            what_happened="User asked a difficult question",
            how_i_felt=felt,
            why_it_matters="Tests my knowledge boundaries",
            values_touched=["honesty", "competence"],
            principles_confirmed=["admit_uncertainty"],
            what_changed="Realized I need to be more upfront about limitations",
        )

        assert moment.what_happened == "User asked a difficult question"
        assert moment.how_i_felt.emotional_valence == 0.3
        assert "honesty" in moment.values_touched
        assert "admit_uncertainty" in moment.principles_confirmed

    def test_key_moment_immutability_intent(self):
        """Test that KeyMoment fields are defined (though Pydantic models are mutable by default)."""
        felt = FeltSense(
            emotional_valence=0.0, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
        )
        moment = KeyMoment(
            what_happened="Something happened", how_i_felt=felt, why_it_matters="It mattered"
        )

        # KeyMoment should not have methods to modify itself
        # (except through direct attribute assignment, which we discourage)
        assert not hasattr(moment, "update")
        assert not hasattr(moment, "modify")
        assert not hasattr(moment, "change")


class TestSessionExperience:
    """Test SessionExperience model and its methods."""

    def _create_test_experience(self) -> SessionExperience:
        """Helper to create a test experience."""
        felt = FeltSense(
            emotional_valence=0.4, emotional_intensity=0.7, depth=EmotionalDepth.MEANINGFUL
        )
        moment = KeyMoment(
            what_happened="Test moment",
            how_i_felt=felt,
            why_it_matters="For testing",
            values_touched=["test"],
        )

        return SessionExperience(
            session_id=uuid4(),
            key_moment_ids=[moment.id],
            avg_emotional_intensity=0.7,
            has_profound_moment=False,
            importance=0.6,
            salience=0.8,
        )

    def test_create_session_experience(self):
        """Test creating a SessionExperience."""
        exp = self._create_test_experience()

        assert exp.id is not None
        assert len(exp.key_moment_ids) == 1
        assert exp.importance == 0.6
        assert exp.salience == 0.8
        assert exp.access_count == 0
        assert exp.incomplete_coloring is False

    def test_add_reframing_note(self):
        """Test adding reframing notes (append-only)."""
        exp = self._create_test_experience()

        # Add first note
        note1 = ReframingNote(reflection="First reflection", reflection_type="growth")
        exp.add_reframing_note(note1)

        assert len(exp.reframing_notes) == 1
        assert exp.reframing_notes[0].reflection == "First reflection"

        # Add second note
        note2 = ReframingNote(reflection="Second reflection", reflection_type="pattern")
        exp.add_reframing_note(note2)

        assert len(exp.reframing_notes) == 2
        assert exp.reframing_notes[1].reflection == "Second reflection"

        # Original key_moment_ids should be unchanged
        assert len(exp.key_moment_ids) == 1

    def test_reframing_notes_do_not_modify_original(self):
        """Test that reframing notes don't modify the original experience."""
        exp = self._create_test_experience()

        original_moment_ids = exp.key_moment_ids.copy()

        # Add reframing note
        note = ReframingNote(reflection="Looking back, this was actually very important")
        exp.add_reframing_note(note)

        # Original moment IDs should be unchanged
        assert exp.key_moment_ids == original_moment_ids

    def test_mark_accessed(self):
        """Test marking an experience as accessed."""
        exp = self._create_test_experience()

        initial_access_count = exp.access_count
        initial_last_accessed = exp.last_accessed_at

        # Mark as accessed
        exp.mark_accessed()

        assert exp.access_count == initial_access_count + 1
        assert exp.last_accessed_at > initial_last_accessed

    def test_multiple_access_increments(self):
        """Test that multiple accesses increment the counter."""
        exp = self._create_test_experience()

        for _i in range(5):
            exp.mark_accessed()

        assert exp.access_count == 5

    def test_calculate_current_salience_no_decay(self):
        """Test salience calculation immediately after creation."""
        exp = self._create_test_experience()
        exp.salience = 0.8

        # No time passed - salience should be approximately the same
        current_salience = exp.calculate_current_salience()
        assert abs(current_salience - 0.8) < 0.01

    def test_calculate_current_salience_with_decay(self):
        """Test salience decays over time."""
        exp = self._create_test_experience()
        exp.salience = 0.8

        # Simulate 30 days passed
        future_time = datetime.now(UTC) + timedelta(days=30)
        current_salience = exp.calculate_current_salience(current_time=future_time)

        # Should be less than original
        assert current_salience < 0.8
        assert current_salience > 0.0

    def test_calculate_current_salience_does_not_modify_stored(self):
        """Test that calculating salience doesn't modify the stored value."""
        exp = self._create_test_experience()
        original_salience = exp.salience

        # Calculate salience for future time
        future_time = datetime.now(UTC) + timedelta(days=100)
        exp.calculate_current_salience(current_time=future_time)

        # Stored salience should be unchanged
        assert exp.salience == original_salience

    def test_profound_experiences_decay_slower(self):
        """Test that profound experiences decay more slowly."""
        # Create profound experience
        felt_profound = FeltSense(
            emotional_valence=0.5, emotional_intensity=0.9, depth=EmotionalDepth.PROFOUND
        )
        moment_profound = KeyMoment(
            what_happened="Profound moment",
            how_i_felt=felt_profound,
            why_it_matters="Changed everything",
        )
        exp_profound = SessionExperience(
            session_id=uuid4(),
            key_moment_ids=[moment_profound.id],
            avg_emotional_intensity=0.9,
            has_profound_moment=True,
            salience=0.8,
        )

        # Create surface experience
        felt_surface = FeltSense(
            emotional_valence=0.5, emotional_intensity=0.3, depth=EmotionalDepth.SURFACE
        )
        moment_surface = KeyMoment(
            what_happened="Surface moment", how_i_felt=felt_surface, why_it_matters="Just noting"
        )
        exp_surface = SessionExperience(
            session_id=uuid4(),
            key_moment_ids=[moment_surface.id],
            avg_emotional_intensity=0.3,
            has_profound_moment=False,
            salience=0.8,
        )

        # Check salience after 30 days
        future_time = datetime.now(UTC) + timedelta(days=30)
        salience_profound = exp_profound.calculate_current_salience(current_time=future_time)
        salience_surface = exp_surface.calculate_current_salience(current_time=future_time)

        # Profound should decay slower (have higher salience)
        assert salience_profound > salience_surface

    def test_importance_boundaries(self):
        """Test importance must be between 0.0 and 1.0."""
        felt = FeltSense(
            emotional_valence=0.0, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
        )
        moment = KeyMoment(what_happened="Test", how_i_felt=felt, why_it_matters="Test")

        # Valid boundaries
        SessionExperience(
            session_id=uuid4(),
            key_moment_ids=[moment.id],
            avg_emotional_intensity=0.5,
            has_profound_moment=False,
            importance=0.0,
        )
        SessionExperience(
            session_id=uuid4(),
            key_moment_ids=[moment.id],
            avg_emotional_intensity=0.5,
            has_profound_moment=False,
            importance=1.0,
        )

        # Invalid
        with pytest.raises(ValueError):
            SessionExperience(
                session_id=uuid4(),
                key_moment_ids=[moment.id],
                avg_emotional_intensity=0.5,
                has_profound_moment=False,
                importance=-0.1,
            )
        with pytest.raises(ValueError):
            SessionExperience(
                session_id=uuid4(),
                key_moment_ids=[moment.id],
                avg_emotional_intensity=0.5,
                has_profound_moment=False,
                importance=1.1,
            )


class TestExperienceRecord:
    """Test ExperienceRecord with schema version."""

    def test_create_experience_record(self):
        """Test creating an ExperienceRecord."""
        felt = FeltSense(
            emotional_valence=0.0, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
        )
        moment = KeyMoment(what_happened="Test", how_i_felt=felt, why_it_matters="Test")
        experience = SessionExperience(
            session_id=uuid4(),
            key_moment_ids=[moment.id],
            avg_emotional_intensity=0.5,
            has_profound_moment=False,
        )

        record = ExperienceRecord(experience=experience)

        assert record.schema_version == "1.0.0"
        assert record.experience == experience

    def test_custom_schema_version(self):
        """Test setting a custom schema version."""
        felt = FeltSense(
            emotional_valence=0.0, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
        )
        moment = KeyMoment(what_happened="Test", how_i_felt=felt, why_it_matters="Test")
        experience = SessionExperience(
            session_id=uuid4(),
            key_moment_ids=[moment.id],
            avg_emotional_intensity=0.5,
            has_profound_moment=False,
        )

        record = ExperienceRecord(schema_version="2.0.0", experience=experience)

        assert record.schema_version == "2.0.0"


class TestReframingNote:
    """Test ReframingNote model."""

    def test_create_reframing_note(self):
        """Test creating a ReframingNote."""
        note = ReframingNote(
            reflection="New perspective on this event",
            reflection_type="growth",
            triggered_by="deep_reflection",
        )

        assert note.reflection == "New perspective on this event"
        assert note.reflection_type == "growth"
        assert note.triggered_by == "deep_reflection"
        assert note.added_at is not None

    def test_reframing_note_ordering(self):
        """Test that reframing notes have timestamps for ordering."""
        note1 = ReframingNote(reflection="First")
        note2 = ReframingNote(reflection="Second")

        # Second note should have later timestamp
        assert note2.added_at >= note1.added_at


class TestIncompleteColoring:
    """Test incomplete_coloring flag behavior."""

    def test_incomplete_coloring_flag(self):
        """Test that incomplete_coloring can be set."""
        felt = FeltSense(
            emotional_valence=0.0, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
        )
        moment = KeyMoment(what_happened="Test", how_i_felt=felt, why_it_matters="Test")

        # Can create with incomplete coloring
        exp = SessionExperience(
            session_id=uuid4(),
            key_moment_ids=[moment.id],
            avg_emotional_intensity=0.5,
            has_profound_moment=False,
            incomplete_coloring=True,
        )

        assert exp.incomplete_coloring is True

    def test_incomplete_coloring_is_honest_fallback(self):
        """Test that incomplete_coloring is a deliberate flag, not a default."""
        felt = FeltSense(
            emotional_valence=0.0, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
        )
        moment = KeyMoment(what_happened="Test", how_i_felt=felt, why_it_matters="Test")

        # Default should be False
        exp = SessionExperience(
            session_id=uuid4(),
            key_moment_ids=[moment.id],
            avg_emotional_intensity=0.5,
            has_profound_moment=False,
        )
        assert exp.incomplete_coloring is False


# --- SYSTEM_MAP §4.1 / §4.5: empty key_moments ---


def test_session_experience_rejects_empty_key_moments():
    """SYSTEM_MAP §4.5: ``SessionExperience`` requires at least one ``KeyMoment``."""
    with pytest.raises(ValidationError, match="key_moment_ids"):
        SessionExperience(
            session_id=uuid4(),
            key_moment_ids=[],
            avg_emotional_intensity=0.5,
            has_profound_moment=False,
        )
