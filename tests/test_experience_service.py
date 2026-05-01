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

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from atman.adapters.storage import InMemoryExperienceStore
from atman.core.models import (
    EmotionalDepth,
    FeltSense,
    KeyMoment,
    SessionExperience,
)
from atman.core.services import ExperienceService


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
            emotional_valence=0.3,
            emotional_intensity=0.7,
            depth=EmotionalDepth.MEANINGFUL
        )
        moment = KeyMoment(
            what_happened="User asked a challenging question",
            how_i_felt=felt,
            why_it_matters="Tests my competence",
            values_touched=["honesty", "competence"],
            principles_confirmed=["admit_uncertainty"],
            what_changed="Became more aware of my limitations"
        )
        
        return SessionExperience(
            session_id=uuid4(),
            key_moments=[moment],
            importance=0.7,
            salience=0.8
        )
    
    def test_create_experience(self, service, sample_experience):
        """Test creating an experience."""
        record = service.create_experience(sample_experience)
        
        assert record.experience.id == sample_experience.id
        assert record.schema_version == "1.0.0"
        assert len(record.experience.key_moments) == 1
    
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
            triggered_by="deep_reflection"
        )
        
        assert updated is not None
        assert len(updated.experience.reframing_notes) == 1
        assert updated.experience.reframing_notes[0].reflection == "Looking back, this was a growth moment"
        assert updated.experience.reframing_notes[0].reflection_type == "growth"
    
    def test_add_multiple_reframing_notes(self, service, sample_experience):
        """Test adding multiple reframing notes."""
        created = service.create_experience(sample_experience)
        
        # Add first note
        service.add_reframing_note(
            experience_id=created.experience.id,
            reflection="First reflection"
        )
        
        # Add second note
        updated = service.add_reframing_note(
            experience_id=created.experience.id,
            reflection="Second reflection"
        )
        
        assert len(updated.experience.reframing_notes) == 2
        assert updated.experience.reframing_notes[0].reflection == "First reflection"
        assert updated.experience.reframing_notes[1].reflection == "Second reflection"
    
    def test_reframing_preserves_original(self, service, sample_experience):
        """Test that reframing doesn't modify original experience."""
        created = service.create_experience(sample_experience)
        original_moment = created.experience.key_moments[0].what_happened
        
        service.add_reframing_note(
            experience_id=created.experience.id,
            reflection="This changes everything!"
        )
        
        updated = service.get_experience(created.experience.id)
        assert updated.experience.key_moments[0].what_happened == original_moment
    
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
            felt = FeltSense(emotional_valence=0.0, emotional_intensity=0.5, depth="surface")
            moment = KeyMoment(
                what_happened=f"Moment {i}",
                how_i_felt=felt,
                why_it_matters="Testing"
            )
            exp = SessionExperience(session_id=session_id, key_moments=[moment])
            service.create_experience(exp)
        
        # Search
        results = service.search_by_session(session_id)
        
        assert len(results) == 3
        assert all(r.experience.session_id == session_id for r in results)
    
    def test_search_by_values(self, service):
        """Test searching by values touched."""
        # Create experience with specific values
        felt = FeltSense(emotional_valence=0.0, emotional_intensity=0.5, depth="surface")
        moment = KeyMoment(
            what_happened="Test",
            how_i_felt=felt,
            why_it_matters="Test",
            values_touched=["honesty", "competence", "service"]
        )
        exp = SessionExperience(session_id=uuid4(), key_moments=[moment])
        service.create_experience(exp)
        
        # Search for experiences touching "honesty"
        results = service.search_by_values(["honesty"])
        
        assert len(results) == 1
        assert "honesty" in results[0].experience.key_moments[0].values_touched
    
    def test_search_by_depth(self, service):
        """Test searching by emotional depth."""
        # Create profound experience
        felt_profound = FeltSense(
            emotional_valence=0.5,
            emotional_intensity=0.9,
            depth=EmotionalDepth.PROFOUND
        )
        moment_profound = KeyMoment(
            what_happened="Profound moment",
            how_i_felt=felt_profound,
            why_it_matters="Changed everything"
        )
        exp_profound = SessionExperience(session_id=uuid4(), key_moments=[moment_profound])
        service.create_experience(exp_profound)
        
        # Create surface experience
        felt_surface = FeltSense(
            emotional_valence=0.0,
            emotional_intensity=0.3,
            depth=EmotionalDepth.SURFACE
        )
        moment_surface = KeyMoment(
            what_happened="Surface moment",
            how_i_felt=felt_surface,
            why_it_matters="Just noting"
        )
        exp_surface = SessionExperience(session_id=uuid4(), key_moments=[moment_surface])
        service.create_experience(exp_surface)
        
        # Search for profound
        results = service.search_by_depth("profound")
        
        assert len(results) == 1
        assert results[0].experience.key_moments[0].how_i_felt.depth == EmotionalDepth.PROFOUND
    
    def test_search_by_date_range(self, service):
        """Test searching by date range."""
        # Create experience with specific timestamp
        felt = FeltSense(emotional_valence=0.0, emotional_intensity=0.5, depth="surface")
        moment = KeyMoment(what_happened="Test", how_i_felt=felt, why_it_matters="Test")
        
        now = datetime.now(timezone.utc)
        exp = SessionExperience(session_id=uuid4(), key_moments=[moment], timestamp=now)
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
            felt = FeltSense(emotional_valence=0.0, emotional_intensity=0.5, depth="surface")
            moment = KeyMoment(what_happened=f"Moment {i}", how_i_felt=felt, why_it_matters="Test")
            exp = SessionExperience(session_id=uuid4(), key_moments=[moment])
            service.create_experience(exp)
        
        # List recent
        results = service.list_recent(limit=3)
        
        assert len(results) == 3
        
        # Should be ordered by timestamp (newest first)
        timestamps = [r.experience.timestamp for r in results]
        assert timestamps == sorted(timestamps, reverse=True)
