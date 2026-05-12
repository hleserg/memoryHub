"""Tests for PostgresStateStore KeyMoment operations."""

import os
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from atman.core.models import EmotionalDepth, FeltSense, KeyMoment

# Skip all tests if psycopg is not installed
try:
    import psycopg  # noqa: F401

    from atman.adapters.state import PostgresStateStore

    PSYCOPG_AVAILABLE = True
except ImportError:
    PSYCOPG_AVAILABLE = False
    PostgresStateStore = Any  # type: ignore[misc]

# Skip all tests in this module if psycopg is not available or if no test database
pytestmark = [
    pytest.mark.skipif(not PSYCOPG_AVAILABLE, reason="psycopg not installed"),
    pytest.mark.skipif(
        not os.environ.get("TEST_DB_URL"),
        reason="TEST_DB_URL not set - skipping PostgresStateStore tests",
    ),
]


@pytest.fixture
def db_url() -> str:
    """Return test database URL from environment."""
    return os.environ.get("TEST_DB_URL", "postgresql://atman@localhost:5432/atman_test")


@pytest.fixture
def store(db_url: str) -> Any:
    """Create a PostgresStateStore instance for testing."""
    from atman.adapters.state import PostgresStateStore

    s = PostgresStateStore(db_url=db_url)
    # Clean up before test
    conn = s._get_conn()
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE public.key_moments")
    conn.commit()
    return s


@pytest.fixture
def sample_key_moment() -> KeyMoment:
    """Create a sample KeyMoment for testing."""
    return KeyMoment(
        id=uuid4(),
        what_happened="User asked me to implement a complex feature",
        when=datetime(2026, 5, 12, 10, 30, 0, tzinfo=UTC),
        how_i_felt=FeltSense(
            emotional_valence=-0.2,
            emotional_intensity=0.6,
            depth=EmotionalDepth.MEANINGFUL,
        ),
        why_it_matters="This challenged my confidence in my capabilities",
        values_touched=["competence", "honesty"],
        principles_confirmed=["admit_when_uncertain"],
        principles_questioned=[],
        what_changed="Realized I need to be more upfront about my limitations",
    )


def test_store_key_moments_single(store: Any, sample_key_moment: KeyMoment) -> None:
    """Test storing a single key moment."""
    session_id = uuid4()

    # Store the moment
    store.store_key_moments(session_id, [sample_key_moment])

    # Retrieve it back
    moments = store.get_key_moments_for_session(session_id)

    assert len(moments) == 1
    assert moments[0].id == sample_key_moment.id
    assert moments[0].what_happened == sample_key_moment.what_happened
    assert moments[0].why_it_matters == sample_key_moment.why_it_matters


def test_store_key_moments_multiple(store: Any) -> None:
    """Test storing multiple key moments for a session."""
    session_id = uuid4()

    moments = [
        KeyMoment(
            id=uuid4(),
            what_happened=f"Event {i}",
            how_i_felt=FeltSense(
                emotional_valence=0.5,
                emotional_intensity=0.7,
                depth=EmotionalDepth.SURFACE,
            ),
            why_it_matters=f"Reason {i}",
        )
        for i in range(3)
    ]

    # Store all moments
    store.store_key_moments(session_id, moments)

    # Retrieve them back
    retrieved = store.get_key_moments_for_session(session_id)

    assert len(retrieved) == 3
    assert {m.id for m in retrieved} == {m.id for m in moments}


def test_get_key_moment_by_id(store: Any, sample_key_moment: KeyMoment) -> None:
    """Test retrieving a key moment by its ID."""
    session_id = uuid4()

    # Store the moment
    store.store_key_moments(session_id, [sample_key_moment])

    # Retrieve by ID
    moment = store.get_key_moment(sample_key_moment.id)

    assert moment is not None
    assert moment.id == sample_key_moment.id
    assert moment.what_happened == sample_key_moment.what_happened


def test_get_key_moment_not_found(store: Any) -> None:
    """Test retrieving a non-existent key moment returns None."""
    random_id = uuid4()
    moment = store.get_key_moment(random_id)
    assert moment is None


def test_get_key_moments_for_session_empty(store: Any) -> None:
    """Test retrieving moments for a session with no moments."""
    session_id = uuid4()
    moments = store.get_key_moments_for_session(session_id)
    assert moments == []


def test_store_key_moments_idempotent(store: Any, sample_key_moment: KeyMoment) -> None:
    """Test that storing the same moment twice is idempotent."""
    session_id = uuid4()

    # Store twice
    store.store_key_moments(session_id, [sample_key_moment])
    store.store_key_moments(session_id, [sample_key_moment])

    # Should still have only one moment
    moments = store.get_key_moments_for_session(session_id)
    assert len(moments) == 1


def test_create_key_moment_raises_on_duplicate(store: Any, sample_key_moment: KeyMoment) -> None:
    """Test that create_key_moment raises ValueError for duplicate IDs."""
    # Store first time using store_key_moments
    session_id = uuid4()
    store.store_key_moments(session_id, [sample_key_moment])

    # Try to create again using create_key_moment
    with pytest.raises(ValueError, match="already exists"):
        store.create_key_moment(sample_key_moment)


def test_list_key_moments_all(store: Any) -> None:
    """Test listing all key moments across sessions."""
    session1 = uuid4()
    session2 = uuid4()

    moment1 = KeyMoment(
        id=uuid4(),
        what_happened="Event 1",
        how_i_felt=FeltSense(
            emotional_valence=0.5,
            emotional_intensity=0.7,
            depth=EmotionalDepth.SURFACE,
        ),
        why_it_matters="Reason 1",
    )
    moment2 = KeyMoment(
        id=uuid4(),
        what_happened="Event 2",
        how_i_felt=FeltSense(
            emotional_valence=0.3,
            emotional_intensity=0.5,
            depth=EmotionalDepth.MEANINGFUL,
        ),
        why_it_matters="Reason 2",
    )

    store.store_key_moments(session1, [moment1])
    store.store_key_moments(session2, [moment2])

    # List all moments
    all_moments = store.list_key_moments()

    assert len(all_moments) >= 2
    moment_ids = {m.id for m in all_moments}
    assert moment1.id in moment_ids
    assert moment2.id in moment_ids


def test_list_key_moments_filtered_by_session(store: Any) -> None:
    """Test listing key moments filtered by session."""
    session1 = uuid4()
    session2 = uuid4()

    moment1 = KeyMoment(
        id=uuid4(),
        what_happened="Event 1",
        how_i_felt=FeltSense(
            emotional_valence=0.5,
            emotional_intensity=0.7,
            depth=EmotionalDepth.SURFACE,
        ),
        why_it_matters="Reason 1",
    )
    moment2 = KeyMoment(
        id=uuid4(),
        what_happened="Event 2",
        how_i_felt=FeltSense(
            emotional_valence=0.3,
            emotional_intensity=0.5,
            depth=EmotionalDepth.MEANINGFUL,
        ),
        why_it_matters="Reason 2",
    )

    store.store_key_moments(session1, [moment1])
    store.store_key_moments(session2, [moment2])

    # List moments for session1 only
    session1_moments = store.list_key_moments(session_id=session1)

    assert len(session1_moments) == 1
    assert session1_moments[0].id == moment1.id


def test_unimplemented_experience_operations(store: Any) -> None:
    """Test that experience operations raise NotImplementedError."""
    from atman.core.models import ExperienceRecord, ReframingNote, SessionExperience

    with pytest.raises(NotImplementedError):
        store.create_experience(
            ExperienceRecord(
                experience=SessionExperience(
                    session_id=uuid4(),
                    key_moment_ids=[uuid4()],
                )
            )
        )

    with pytest.raises(NotImplementedError):
        store.get_experience(uuid4())

    with pytest.raises(NotImplementedError):
        store.add_reframing_note(
            uuid4(), ReframingNote(reflection="test", reflection_type="general")
        )

    with pytest.raises(NotImplementedError):
        store.mark_accessed(uuid4())

    with pytest.raises(NotImplementedError):
        store.search_experiences()

    with pytest.raises(NotImplementedError):
        store.list_recent_experiences()


def test_unimplemented_identity_operations(store: Any) -> None:
    """Test that identity operations raise NotImplementedError."""
    from atman.core.models import Identity, IdentitySnapshot

    with pytest.raises(NotImplementedError):
        store.load_identity(uuid4())

    with pytest.raises(NotImplementedError):
        store.save_identity(Identity(id=uuid4()))

    with pytest.raises(NotImplementedError):
        store.create_identity_snapshot(
            IdentitySnapshot(
                id=uuid4(),
                identity_id=uuid4(),
                timestamp=datetime.now(UTC),
                identity_snapshot=Identity(id=uuid4()),
            )
        )

    with pytest.raises(NotImplementedError):
        store.list_identity_snapshots(uuid4())


def test_unimplemented_narrative_operations(store: Any) -> None:
    """Test that narrative operations raise NotImplementedError."""
    from atman.core.models import LayerType, NarrativeDocument, NarrativeLayer

    with pytest.raises(NotImplementedError):
        store.load_narrative(uuid4())

    with pytest.raises(NotImplementedError):
        store.save_narrative(
            NarrativeDocument(
                id=uuid4(),
                identity_id=uuid4(),
                core_layer=NarrativeLayer(content="", layer_type=LayerType.CORE),
                recent_layer=NarrativeLayer(content="", layer_type=LayerType.RECENT),
            )
        )

    with pytest.raises(NotImplementedError):
        store.archive_narrative(uuid4(), "test")

    with pytest.raises(NotImplementedError):
        store.list_archived_narratives(uuid4())


def test_unimplemented_eigenstate_operations(store: Any) -> None:
    """Test that eigenstate operations raise NotImplementedError."""
    from atman.core.models import Eigenstate

    with pytest.raises(NotImplementedError):
        store.save_eigenstate(
            Eigenstate(
                id=uuid4(),
                session_id=uuid4(),
                identity_id=uuid4(),
                timestamp=datetime.now(UTC),
            )
        )

    with pytest.raises(NotImplementedError):
        store.load_latest_eigenstate()


def test_context_manager(db_url: str, sample_key_moment: KeyMoment) -> None:
    """Test that PostgresStateStore works as a context manager."""
    from atman.adapters.state import PostgresStateStore

    session_id = uuid4()

    with PostgresStateStore(db_url=db_url) as store:
        store.store_key_moments(session_id, [sample_key_moment])
        moments = store.get_key_moments_for_session(session_id)
        assert len(moments) == 1

    # Connection should be closed after exiting context
    # (We can't easily test this without accessing private state)
