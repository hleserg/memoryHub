"""
Tests for experience storage adapters.

Tests both JSONL and in-memory stores to ensure they implement
the StateStore interface correctly.
"""

import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

from atman.adapters.storage import InMemoryExperienceStore, JsonlExperienceStore
from atman.core.models import (
    EmotionalDepth,
    ExperienceRecord,
    FeltSense,
    KeyMoment,
    ReframingNote,
    SessionExperience,
)
from atman.core.ports import DepthQuery, SessionExperienceQuery, ValuesTouchedQuery


class StoreTestMixin:
    """Mixin with common tests for all store implementations."""

    @pytest.fixture
    def store(self):
        """Override in subclass to provide store instance."""
        raise NotImplementedError

    @pytest.fixture
    def sample_record(self):
        """Create a sample experience record."""
        felt = FeltSense(
            emotional_valence=0.3, emotional_intensity=0.7, depth=EmotionalDepth.MEANINGFUL
        )
        moment = KeyMoment(
            what_happened="Test moment",
            how_i_felt=felt,
            why_it_matters="For testing",
            values_touched=["test", "quality"],
        )
        experience = SessionExperience(
            session_id=uuid4(), key_moments=[moment], importance=0.7, salience=0.8
        )

        return ExperienceRecord(experience=experience)

    def test_create_and_get(self, store, sample_record):
        """Test creating and retrieving an experience."""
        created = store.create_experience(sample_record)

        retrieved = store.get_experience(created.experience.id)

        assert retrieved is not None
        assert retrieved.experience.id == created.experience.id
        assert len(retrieved.experience.key_moments) == 1

    def test_get_nonexistent(self, store):
        """Test getting a non-existent experience returns None."""
        result = store.get_experience(uuid4())
        assert result is None

    def test_create_duplicate_fails(self, store, sample_record):
        """Test that creating duplicate experience fails."""
        store.create_experience(sample_record)

        with pytest.raises(ValueError, match="already exists"):
            store.create_experience(sample_record)

    def test_add_reframing_note(self, store, sample_record):
        """Test adding a reframing note."""
        created = store.create_experience(sample_record)

        note = ReframingNote(reflection="New perspective")
        updated = store.add_reframing_note(created.experience.id, note)

        assert updated is not None
        assert len(updated.experience.reframing_notes) == 1
        assert updated.experience.reframing_notes[0].reflection == "New perspective"

    def test_add_reframing_note_to_nonexistent(self, store):
        """Test adding note to non-existent experience."""
        note = ReframingNote(reflection="Test")
        result = store.add_reframing_note(uuid4(), note)

        assert result is None

    def test_mark_accessed(self, store, sample_record):
        """Test marking an experience as accessed."""
        created = store.create_experience(sample_record)
        initial_count = created.experience.access_count

        updated = store.mark_accessed(created.experience.id)

        assert updated is not None
        assert updated.experience.access_count == initial_count + 1

    def test_mark_accessed_nonexistent(self, store):
        """Test marking non-existent experience."""
        result = store.mark_accessed(uuid4())
        assert result is None

    def test_search_by_session(self, store):
        """Test searching by session ID."""
        session_id = uuid4()

        # Create experiences
        for i in range(3):
            felt = FeltSense(
                emotional_valence=0.0, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
            )
            moment = KeyMoment(what_happened=f"Moment {i}", how_i_felt=felt, why_it_matters="Test")
            exp = SessionExperience(session_id=session_id, key_moments=[moment])
            record = ExperienceRecord(experience=exp)
            store.create_experience(record)

        query = SessionExperienceQuery(session_id=session_id)
        results = store.search_experiences(query=query)

        assert len(results) == 3

    def test_search_by_values(self, store):
        """Test searching by values touched."""
        felt = FeltSense(
            emotional_valence=0.0, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
        )
        moment = KeyMoment(
            what_happened="Test",
            how_i_felt=felt,
            why_it_matters="Test",
            values_touched=["honesty", "competence"],
        )
        exp = SessionExperience(session_id=uuid4(), key_moments=[moment])
        record = ExperienceRecord(experience=exp)
        store.create_experience(record)

        query = ValuesTouchedQuery(values=["honesty"])
        results = store.search_experiences(query=query)

        assert len(results) == 1

    def test_search_by_depth(self, store):
        """Test searching by emotional depth."""
        felt = FeltSense(
            emotional_valence=0.5, emotional_intensity=0.9, depth=EmotionalDepth.PROFOUND
        )
        moment = KeyMoment(what_happened="Profound", how_i_felt=felt, why_it_matters="Changed me")
        exp = SessionExperience(session_id=uuid4(), key_moments=[moment])
        record = ExperienceRecord(experience=exp)
        store.create_experience(record)

        query = DepthQuery(depth="profound")
        results = store.search_experiences(query=query)

        assert len(results) == 1

    def test_list_recent(self, store):
        """Test listing recent experiences."""
        for i in range(5):
            felt = FeltSense(
                emotional_valence=0.0, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
            )
            moment = KeyMoment(what_happened=f"Moment {i}", how_i_felt=felt, why_it_matters="Test")
            exp = SessionExperience(session_id=uuid4(), key_moments=[moment])
            record = ExperienceRecord(experience=exp)
            store.create_experience(record)

        results = store.list_recent_experiences(limit=3)

        assert len(results) == 3


class TestInMemoryExperienceStore(StoreTestMixin):
    """Test in-memory experience store."""

    @pytest.fixture
    def store(self):
        """Provide in-memory store instance."""
        return InMemoryExperienceStore()

    def test_clear(self, store, sample_record):
        """Test clearing the store."""
        store.create_experience(sample_record)
        assert store.count() == 1

        store.clear()
        assert store.count() == 0

    def test_count(self, store, sample_record):
        """Test counting experiences."""
        assert store.count() == 0

        store.create_experience(sample_record)
        assert store.count() == 1


class TestJsonlExperienceStore(StoreTestMixin):
    """Test JSONL experience store."""

    @pytest.fixture
    def store(self):
        """Provide JSONL store instance with temp file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "test_experiences.jsonl"
            yield JsonlExperienceStore(storage_path)

    def test_persistence(self, sample_record):
        """Test that data persists across store instances."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "test_experiences.jsonl"

            # Create experience in first instance
            store1 = JsonlExperienceStore(storage_path)
            created = store1.create_experience(sample_record)
            experience_id = created.experience.id

            # Retrieve in second instance
            store2 = JsonlExperienceStore(storage_path)
            retrieved = store2.get_experience(experience_id)

            assert retrieved is not None
            assert retrieved.experience.id == experience_id

    def test_file_creation(self):
        """Test that storage file is created if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "new" / "experiences.jsonl"

            JsonlExperienceStore(storage_path)

            assert storage_path.exists()
            assert storage_path.parent.exists()

    def test_handles_empty_lines(self, sample_record):
        """Test that empty lines in file are handled gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "test_experiences.jsonl"

            # Create store and add experience
            store = JsonlExperienceStore(storage_path)
            store.create_experience(sample_record)

            # Add empty line to file
            with open(storage_path, "a", encoding="utf-8") as f:
                f.write("\n\n")

            # Should still work
            results = store.list_recent_experiences()
            assert len(results) == 1
