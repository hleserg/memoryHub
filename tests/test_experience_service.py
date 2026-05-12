"""
Tests for ExperienceService.

Tests cover:
- Creating experiences
- Retrieving experiences
- Adding reframing notes
- Marking access
- Searching by various criteria
- Salience calculation
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from atman.adapters.storage import InMemoryExperienceStore
from atman.core.models import (
    EmotionalDepth,
    FeltSense,
    KeyMoment,
    SessionExperience,
)
from atman.core.services import ExperienceService


def _make_session_experience(
    moment: KeyMoment,
    session_id: UUID | None = None,
    **kwargs: object,
) -> SessionExperience:
    """Helper to create SessionExperience with new key_moment_ids field."""
    avg_intensity = moment.how_i_felt.emotional_intensity
    is_profound = moment.how_i_felt.depth == EmotionalDepth.PROFOUND

    return SessionExperience(
        session_id=session_id or uuid4(),
        key_moment_ids=[moment.id],
        avg_emotional_intensity=avg_intensity,
        has_profound_moment=is_profound,
        **kwargs,  # type: ignore[arg-type]
    )


class TestExperienceService:
    """Test ExperienceService operations."""

    @pytest.fixture
    def service(self):
        """Create a service with in-memory storage."""
        store = InMemoryExperienceStore()
        return ExperienceService(store)

    @pytest.fixture
    def sample_experience(self):
        """Create a sample experience for testing."""
        felt = FeltSense(
            emotional_valence=0.3, emotional_intensity=0.7, depth=EmotionalDepth.MEANINGFUL
        )
        moment = KeyMoment(
            what_happened="User asked a challenging question",
            how_i_felt=felt,
            why_it_matters="Tests my competence",
            values_touched=["honesty", "competence"],
            principles_confirmed=["admit_uncertainty"],
            what_changed="Became more aware of my limitations",
        )

        return SessionExperience(
            session_id=uuid4(),
            key_moment_ids=[moment.id],
            avg_emotional_intensity=0.7,
            has_profound_moment=False,
            importance=0.7,
            salience=0.8,
        )

    def test_create_experience(self, service, sample_experience):
        """Test creating an experience."""
        record = service.create_experience(sample_experience)

        assert record.experience.id == sample_experience.id
        assert record.schema_version == "1.0.0"
        assert len(record.experience.key_moment_ids) == 1

    def test_create_duplicate_experience_fails(self, service, sample_experience):
        """Test that creating duplicate experience raises error."""
        service.create_experience(sample_experience)

        with pytest.raises(ValueError, match="already exists"):
            service.create_experience(sample_experience)

    def test_get_experience(self, service, sample_experience):
        """Test retrieving an experience by ID."""
        created = service.create_experience(sample_experience)

        retrieved = service.get_experience(created.experience.id)

        assert retrieved is not None
        assert retrieved.experience.id == created.experience.id

    def test_get_nonexistent_experience(self, service):
        """Test getting a non-existent experience returns None."""
        result = service.get_experience(uuid4())
        assert result is None

    def test_add_reframing_note(self, service, sample_experience):
        """Test adding a reframing note."""
        created = service.create_experience(sample_experience)

        updated = service.add_reframing_note(
            experience_id=created.experience.id,
            reflection="Looking back, this was a growth moment",
            reflection_type="growth",
            triggered_by="deep_reflection",
        )

        assert updated is not None
        assert len(updated.experience.reframing_notes) == 1
        assert (
            updated.experience.reframing_notes[0].reflection
            == "Looking back, this was a growth moment"
        )
        assert updated.experience.reframing_notes[0].reflection_type == "growth"

    def test_add_multiple_reframing_notes(self, service, sample_experience):
        """Test adding multiple reframing notes."""
        created = service.create_experience(sample_experience)

        # Add first note
        service.add_reframing_note(
            experience_id=created.experience.id, reflection="First reflection"
        )

        # Add second note
        updated = service.add_reframing_note(
            experience_id=created.experience.id, reflection="Second reflection"
        )

        assert len(updated.experience.reframing_notes) == 2
        assert updated.experience.reframing_notes[0].reflection == "First reflection"
        assert updated.experience.reframing_notes[1].reflection == "Second reflection"

    def test_reframing_preserves_original(self, service, sample_experience):
        """Test that reframing doesn't modify original experience."""
        created = service.create_experience(sample_experience)
        original_moment_ids = created.experience.key_moment_ids.copy()

        service.add_reframing_note(
            experience_id=created.experience.id, reflection="This changes everything!"
        )

        updated = service.get_experience(created.experience.id)
        assert updated is not None
        # Key moment IDs should not change
        assert updated.experience.key_moment_ids == original_moment_ids

    def test_mark_accessed(self, service, sample_experience):
        """Test marking an experience as accessed."""
        created = service.create_experience(sample_experience)
        initial_count = created.experience.access_count

        updated = service.mark_accessed(created.experience.id)

        assert updated is not None
        assert updated.experience.access_count == initial_count + 1

    def test_calculate_current_salience(self, service, sample_experience):
        """Test calculating current salience."""
        created = service.create_experience(sample_experience)

        salience = service.calculate_current_salience(created.experience.id)

        assert salience is not None
        assert 0.0 <= salience <= 1.0

    def test_calculate_salience_nonexistent(self, service):
        """Test calculating salience for non-existent experience."""
        result = service.calculate_current_salience(uuid4())
        assert result is None

    def test_search_by_session(self, service):
        """Test searching by session ID."""
        session_id = uuid4()

        # Create experiences for the session
        for i in range(3):
            felt = FeltSense(
                emotional_valence=0.0, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
            )
            moment = KeyMoment(
                what_happened=f"Moment {i}", how_i_felt=felt, why_it_matters="Testing"
            )
            exp = SessionExperience(
                session_id=session_id,
                key_moment_ids=[moment.id],
                avg_emotional_intensity=0.5,
                has_profound_moment=False,
            )
            service.create_experience(exp)

        # Search
        results = service.search_by_session(session_id)

        assert len(results) == 3
        assert all(r.experience.session_id == session_id for r in results)

    def test_search_by_values(self, service):
        """Test searching by values touched."""
        # Create experience with specific values
        felt = FeltSense(
            emotional_valence=0.0, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
        )
        moment = KeyMoment(
            what_happened="Test",
            how_i_felt=felt,
            why_it_matters="Test",
            values_touched=["honesty", "competence", "service"],
        )
        # Store the moment first so we can reference it
        exp = SessionExperience(
            session_id=uuid4(),
            key_moment_ids=[moment.id],
            avg_emotional_intensity=0.5,
            has_profound_moment=False,
        )
        created = service.create_experience(exp)
        # Store the moment so queries can find it
        service.store.store_key_moments(created.experience.session_id, [moment])

        # Search for experiences touching "honesty"
        results = service.search_by_values(["honesty"])

        assert len(results) == 1
        # Verify by fetching the moment
        retrieved_moment = service.store.get_key_moment(results[0].experience.key_moment_ids[0])
        assert retrieved_moment is not None
        assert "honesty" in retrieved_moment.values_touched

    def test_search_by_depth(self, service):
        """Test searching by emotional depth."""
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
        )
        created_profound = service.create_experience(exp_profound)
        service.store.store_key_moments(created_profound.experience.session_id, [moment_profound])

        # Create surface experience
        felt_surface = FeltSense(
            emotional_valence=0.0, emotional_intensity=0.3, depth=EmotionalDepth.SURFACE
        )
        moment_surface = KeyMoment(
            what_happened="Surface moment", how_i_felt=felt_surface, why_it_matters="Just noting"
        )
        exp_surface = SessionExperience(
            session_id=uuid4(),
            key_moment_ids=[moment_surface.id],
            avg_emotional_intensity=0.3,
            has_profound_moment=False,
        )
        created_surface = service.create_experience(exp_surface)
        service.store.store_key_moments(created_surface.experience.session_id, [moment_surface])

        # Search for profound
        results = service.search_by_depth("profound")

        assert len(results) == 1
        retrieved_moment = service.store.get_key_moment(results[0].experience.key_moment_ids[0])
        assert retrieved_moment is not None
        assert retrieved_moment.how_i_felt.depth == EmotionalDepth.PROFOUND

    def test_search_by_date_range(self, service):
        """Test searching by date range."""
        # Create experience with specific timestamp
        felt = FeltSense(
            emotional_valence=0.0, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
        )
        moment = KeyMoment(what_happened="Test", how_i_felt=felt, why_it_matters="Test")

        now = datetime.now(UTC)
        exp = SessionExperience(
            session_id=uuid4(),
            key_moment_ids=[moment.id],
            avg_emotional_intensity=0.5,
            has_profound_moment=False,
            timestamp=now,
        )
        service.create_experience(exp)

        # Search in range that includes this experience
        start = now - timedelta(days=1)
        end = now + timedelta(days=1)
        results = service.search_by_date_range(start, end)

        assert len(results) == 1

        # Search in range that doesn't include it
        start = now + timedelta(days=1)
        end = now + timedelta(days=2)
        results = service.search_by_date_range(start, end)

        assert len(results) == 0

    def test_list_recent(self, service):
        """Test listing recent experiences."""
        # Create several experiences
        for i in range(5):
            felt = FeltSense(
                emotional_valence=0.0, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
            )
            moment = KeyMoment(what_happened=f"Moment {i}", how_i_felt=felt, why_it_matters="Test")
            exp = SessionExperience(
                session_id=uuid4(),
                key_moment_ids=[moment.id],
                avg_emotional_intensity=0.5,
                has_profound_moment=False,
            )
            service.create_experience(exp)

        # List recent
        results = service.list_recent(limit=3)

        assert len(results) == 3

        # Should be ordered by timestamp (newest first)
        timestamps = [r.experience.timestamp for r in results]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_list_by_fact(self, service):
        """Test listing experiences by fact reference."""
        fact_id = uuid4()
        other_fact_id = uuid4()

        # Create experience with fact reference
        felt = FeltSense(
            emotional_valence=0.3, emotional_intensity=0.7, depth=EmotionalDepth.MEANINGFUL
        )
        moment_with_fact = KeyMoment(
            what_happened="Used a specific fact",
            how_i_felt=felt,
            why_it_matters="Fact helped me respond",
            fact_refs=[fact_id],
        )
        exp_with_fact = SessionExperience(
            session_id=uuid4(),
            key_moment_ids=[moment_with_fact.id],
            avg_emotional_intensity=0.7,
            has_profound_moment=False,
        )
        created_with_fact = service.create_experience(exp_with_fact)
        service.store.store_key_moments(created_with_fact.experience.session_id, [moment_with_fact])

        # Create experience without fact reference
        moment_without_fact = KeyMoment(
            what_happened="Didn't use the fact", how_i_felt=felt, why_it_matters="Just happened"
        )
        exp_without_fact = SessionExperience(
            session_id=uuid4(),
            key_moment_ids=[moment_without_fact.id],
            avg_emotional_intensity=0.7,
            has_profound_moment=False,
        )
        service.create_experience(exp_without_fact)

        # Create another experience with different fact
        moment_other_fact = KeyMoment(
            what_happened="Used different fact",
            how_i_felt=felt,
            why_it_matters="Other fact helped",
            fact_refs=[other_fact_id],
        )
        exp_other_fact = SessionExperience(
            session_id=uuid4(),
            key_moment_ids=[moment_other_fact.id],
            avg_emotional_intensity=0.7,
            has_profound_moment=False,
        )
        service.create_experience(exp_other_fact)

        # Search by fact_id
        results = service.list_by_fact(fact_id, limit=10)

        assert len(results) == 1
        assert results[0].experience.id == created_with_fact.experience.id
        # Verify by fetching the moment
        retrieved_moment = service.store.get_key_moment(results[0].experience.key_moment_ids[0])
        assert retrieved_moment is not None
        assert fact_id in retrieved_moment.fact_refs

    def test_list_by_fact_multiple_matches(self, service):
        """Test listing multiple experiences referencing the same fact."""
        fact_id = uuid4()

        felt = FeltSense(
            emotional_valence=0.0, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
        )

        # Create three experiences with the same fact
        exp_ids = []
        for i in range(3):
            moment = KeyMoment(
                what_happened=f"Used fact {i}",
                how_i_felt=felt,
                why_it_matters="Testing",
                fact_refs=[fact_id],
            )
            exp = SessionExperience(
                session_id=uuid4(),
                key_moment_ids=[moment.id],
                avg_emotional_intensity=0.5,
                has_profound_moment=False,
            )
            record = service.create_experience(exp)
            service.store.store_key_moments(record.experience.session_id, [moment])
            exp_ids.append(record.experience.id)

        # List by fact with limit=2
        results = service.list_by_fact(fact_id, limit=2)

        assert len(results) == 2
        # Should be ordered by timestamp descending (newest first)
        timestamps = [r.experience.timestamp for r in results]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_list_by_fact_nonexistent(self, service):
        """Test listing by non-existent fact returns empty list."""
        # Create experience without fact refs
        felt = FeltSense(
            emotional_valence=0.0, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
        )
        moment = KeyMoment(what_happened="No facts", how_i_felt=felt, why_it_matters="Testing")
        exp = SessionExperience(
            session_id=uuid4(),
            key_moment_ids=[moment.id],
            avg_emotional_intensity=0.5,
            has_profound_moment=False,
        )
        service.create_experience(exp)

        # Search for non-existent fact
        results = service.list_by_fact(uuid4())

        assert len(results) == 0


# --- SYSTEM_MAP §1.3 / §4.2 P2 additions ---


class TestExperienceServiceP2:
    """SYSTEM_MAP §1.3 + §4.2: additional invariants on the experience service."""

    @pytest.fixture
    def service(self):
        store = InMemoryExperienceStore()
        return ExperienceService(store)

    @pytest.fixture
    def sample_experience(self):
        felt = FeltSense(
            emotional_valence=0.3, emotional_intensity=0.7, depth=EmotionalDepth.MEANINGFUL
        )
        moment = KeyMoment(
            what_happened="P2 sample event",
            how_i_felt=felt,
            why_it_matters="P2 test",
        )
        return SessionExperience(
            session_id=uuid4(),
            key_moment_ids=[moment.id],
            avg_emotional_intensity=0.7,
            has_profound_moment=False,
            importance=0.5,
            salience=1.0,
        )

    def test_add_reframing_note_duplicate_triggered_by_returns_unchanged_record(
        self, service, sample_experience
    ):
        """SYSTEM_MAP §4.2: re-using ``triggered_by`` does not append a duplicate note."""
        service.create_experience(sample_experience)
        first = service.add_reframing_note(
            experience_id=sample_experience.id,
            reflection="First reflection text",
            triggered_by="run-A",
        )
        assert first is not None
        assert len(first.experience.reframing_notes) == 1

        second = service.add_reframing_note(
            experience_id=sample_experience.id,
            reflection="Different reflection but same trigger",
            triggered_by="run-A",
        )
        assert second is not None
        # No additional note appended; the first reflection text is preserved.
        assert len(second.experience.reframing_notes) == 1
        assert second.experience.reframing_notes[0].reflection == "First reflection text"

    def test_calculate_current_salience_decays_with_age(self, service, sample_experience):
        """SYSTEM_MAP §1.3: salience for the same record strictly decreases with age."""
        service.create_experience(sample_experience)

        ref = sample_experience.last_accessed_at
        s_now = service.calculate_current_salience(sample_experience.id, current_time=ref)
        s_later = service.calculate_current_salience(
            sample_experience.id, current_time=ref + timedelta(days=10)
        )
        s_much_later = service.calculate_current_salience(
            sample_experience.id, current_time=ref + timedelta(days=60)
        )
        assert s_now is not None and s_later is not None and s_much_later is not None
        assert s_now > s_later > s_much_later
