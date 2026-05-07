"""
Tests for Narrative Service.

Tests cover:
- Narrative creation and updates
- First-person validation
- Archive functionality
- Markdown rendering and validation
"""

from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import pytest

from atman.adapters.storage import FileStateStore
from atman.core.models import (
    Eigenstate,
    Identity,
    LayerType,
    NarrativeThread,
)
from atman.core.services import NarrativeService


def test_create_narrative_from_identity():
    """Test creating narrative from identity."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = NarrativeService(store)

        identity = Identity(
            id=uuid4(),
            self_description="I am learning who I am.",
        )

        narrative = service.create_narrative(identity)

        assert narrative.identity_id == identity.id
        assert narrative.core_layer.layer_type == LayerType.CORE
        assert narrative.recent_layer.layer_type == LayerType.RECENT


def test_update_recent_layer():
    """Test updating recent layer."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = NarrativeService(store)

        identity = Identity(id=uuid4())
        service.create_narrative(identity)

        # Update recent layer
        updated = service.update_recent_layer(identity.id, "I just completed a significant task.")

        assert "completed a significant task" in updated.recent_layer.content


def test_update_recent_layer_validates_first_person():
    """Test that updating recent layer validates first-person."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = NarrativeService(store)

        identity = Identity(id=uuid4())
        service.create_narrative(identity)

        # Third-person content should fail
        with pytest.raises(ValueError, match="first person"):
            service.update_recent_layer(identity.id, "The agent completed a task.")


def test_update_core_layer():
    """Test updating core layer."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = NarrativeService(store)

        identity = Identity(id=uuid4())
        service.create_narrative(identity)

        # Update core layer
        updated = service.update_core_layer(identity.id, "I have grown significantly.")

        assert "grown significantly" in updated.core_layer.content


def test_update_core_layer_archives_old():
    """Test that updating core layer archives old narrative."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = NarrativeService(store)

        identity = Identity(id=uuid4())
        service.create_narrative(identity)

        # Update core layer
        service.update_core_layer(identity.id, "I have changed fundamentally.")

        # Check archive
        archives = store.list_archived_narratives(identity.id)
        assert len(archives) == 1
        assert archives[0][1] == "Core layer update"  # reason


def test_add_thread():
    """Test adding narrative thread."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = NarrativeService(store)

        identity = Identity(id=uuid4())
        service.create_narrative(identity)

        # Add thread
        thread = NarrativeThread(
            title="Learning uncertainty",
            description="Journey of growth",
        )
        updated = service.add_thread(identity.id, thread)

        assert len(updated.threads) == 1
        assert updated.threads[0].title == "Learning uncertainty"


def test_close_thread_requires_reason():
    """Test that closing thread requires reason."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = NarrativeService(store)

        identity = Identity(id=uuid4())
        service.create_narrative(identity)

        thread = NarrativeThread(title="Test thread")
        updated = service.add_thread(identity.id, thread)

        thread_id = updated.threads[0].id

        # Cannot close without reason
        with pytest.raises(ValueError, match="closure_reason is required"):
            service.close_thread(identity.id, thread_id, "")

        # Close with reason
        closed = service.close_thread(identity.id, thread_id, "Resolved")

        assert not closed.threads[0].is_active
        assert closed.threads[0].closure_reason == "Resolved"


def test_render_to_file():
    """Test rendering narrative to file."""
    with TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        store = FileStateStore(workspace)
        service = NarrativeService(store)

        identity = Identity(id=uuid4(), self_description="I am learning.")
        service.create_narrative(identity)

        # Render to file
        output_path = workspace / "NARRATIVE.md"
        result_path = service.render_to_file(identity.id, output_path)

        assert result_path.exists()
        content = result_path.read_text()

        # Should have mandatory sections
        assert "## CORE LAYER" in content
        assert "## RECENT LAYER" in content


def test_validate_narrative_file_valid():
    """Test validating valid narrative file."""
    with TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        store = FileStateStore(workspace)
        service = NarrativeService(store)

        # Create valid narrative
        narrative_path = workspace / "NARRATIVE.md"
        narrative_path.write_text(
            """# NARRATIVE

## CORE LAYER

I am learning who I am.

## RECENT LAYER

I just completed implementation.
""",
            encoding="utf-8",
        )

        is_valid, issues = service.validate_narrative_file(narrative_path)

        assert is_valid
        assert len(issues) == 0


def test_validate_narrative_file_missing_sections():
    """Test validating narrative with missing sections."""
    with TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        store = FileStateStore(workspace)
        service = NarrativeService(store)

        # Create invalid narrative - missing RECENT LAYER
        narrative_path = workspace / "NARRATIVE.md"
        narrative_path.write_text(
            """# NARRATIVE

## CORE LAYER

I am learning.
""",
            encoding="utf-8",
        )

        is_valid, issues = service.validate_narrative_file(narrative_path)

        assert not is_valid
        assert any("RECENT LAYER" in issue for issue in issues)


def test_validate_narrative_file_third_person():
    """Test validating narrative with third-person content."""
    with TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        store = FileStateStore(workspace)
        service = NarrativeService(store)

        # Create narrative with third-person content
        narrative_path = workspace / "NARRATIVE.md"
        narrative_path.write_text(
            """# NARRATIVE

## CORE LAYER

The agent is learning.

## RECENT LAYER

Atman did something.
""",
            encoding="utf-8",
        )

        is_valid, issues = service.validate_narrative_file(narrative_path)

        assert not is_valid
        assert any("the agent" in issue.lower() for issue in issues)
        assert any("atman did" in issue.lower() for issue in issues)


def test_update_from_eigenstate():
    """Test updating narrative from eigenstate."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = NarrativeService(store)

        identity = Identity(id=uuid4())
        service.create_narrative(identity)

        # Create eigenstate
        eigenstate = Eigenstate(
            session_id=uuid4(),
            emotional_tone=0.3,
            session_summary="I implemented the identity store.",
            key_insight="Bootstrap must be honest about lack of data.",
            open_threads=["Need to add tests"],
        )

        # Update narrative
        updated = service.update_from_identity_and_eigenstate(identity, eigenstate)

        # Should contain eigenstate info
        assert "implemented" in updated.recent_layer.content.lower()


def test_sync_threads_from_eigenstate():
    """Test that threads are synced from eigenstate."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = NarrativeService(store)

        identity = Identity(id=uuid4())
        service.create_narrative(identity)

        # Create eigenstate with open threads
        eigenstate = Eigenstate(
            session_id=uuid4(),
            session_summary="Working on implementation",
            open_threads=["Need to finish tests", "Need to write docs"],
        )

        # Update narrative
        updated = service.update_from_identity_and_eigenstate(identity, eigenstate)

        # Should have created threads
        assert len(updated.threads) >= 1
        thread_titles = [t.title for t in updated.threads]
        assert any("tests" in title.lower() for title in thread_titles)


def test_get_narrative_returns_none_when_no_narrative_exists():
    """get_narrative returns None when no narrative is stored."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = NarrativeService(store)
        result = service.get_narrative(uuid4())
        assert result is None


def test_update_from_identity_creates_narrative_when_none_exists():
    """update_from_identity_and_eigenstate bootstraps a new narrative if none stored."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = NarrativeService(store)
        identity = Identity(id=uuid4(), self_description="I bootstrap.")
        doc = service.update_from_identity_and_eigenstate(identity)
        assert doc is not None
        assert "bootstrap" in doc.core_layer.content.lower()


def test_update_from_identity_without_eigenstate_skips_archive_and_recent():
    """Calling update_from_identity_and_eigenstate with eigenstate=None skips archive/recent."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = NarrativeService(store)
        identity = Identity(id=uuid4(), self_description="I exist.")
        service.create_narrative(identity)
        updated = service.update_from_identity_and_eigenstate(identity, eigenstate=None)
        assert updated is not None
        assert store.list_archived_narratives(identity.id) == []


def test_update_from_identity_with_eigenstate_no_summary_skips_archive():
    """Eigenstate without session_summary does not trigger archive."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = NarrativeService(store)
        identity = Identity(id=uuid4(), self_description="I reflect.")
        service.create_narrative(identity)
        eigenstate = Eigenstate(session_id=uuid4(), session_summary="", open_threads=[])
        updated = service.update_from_identity_and_eigenstate(identity, eigenstate)
        assert updated is not None
        assert store.list_archived_narratives(identity.id) == []


def test_update_from_identity_changed_core_layer():
    """update_from_identity_and_eigenstate updates core layer when content changes."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = NarrativeService(store)
        identity = Identity(id=uuid4(), self_description="Old description.")
        service.create_narrative(identity)
        identity_updated = Identity(
            id=identity.id, self_description="New description after growth."
        )
        updated = service.update_from_identity_and_eigenstate(identity_updated, eigenstate=None)
        assert "New description" in updated.core_layer.content


def test_update_recent_layer_raises_when_narrative_not_found():
    """update_recent_layer raises ValueError when no narrative exists for identity."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = NarrativeService(store)
        with pytest.raises(ValueError, match="not found"):
            service.update_recent_layer(uuid4(), "I learned something today.")


def test_update_core_layer_raises_when_narrative_not_found():
    """update_core_layer raises ValueError when no narrative exists for identity."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = NarrativeService(store)
        with pytest.raises(ValueError, match="not found"):
            service.update_core_layer(uuid4(), "I am a new agent.")


def test_add_thread_raises_when_narrative_not_found():
    """add_thread raises ValueError when no narrative exists for identity."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = NarrativeService(store)
        thread = NarrativeThread(title="Test thread", description="desc", current_state="open")
        with pytest.raises(ValueError, match="not found"):
            service.add_thread(uuid4(), thread)


def test_close_thread_raises_when_narrative_not_found():
    """close_thread raises ValueError when no narrative exists for identity."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = NarrativeService(store)
        with pytest.raises(ValueError, match="not found"):
            service.close_thread(uuid4(), uuid4(), "done")


def test_render_to_file_raises_when_narrative_not_found():
    """render_to_file raises ValueError when no narrative exists for identity."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = NarrativeService(store)
        out_path = Path(tmpdir) / "NARRATIVE.md"
        with pytest.raises(ValueError, match="not found"):
            service.render_to_file(uuid4(), out_path)


def test_generate_core_layer_includes_principles_and_open_questions():
    """_generate_core_layer_from_identity includes principles and open questions."""
    from atman.core.models.identity import OpenQuestion, Principle

    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = NarrativeService(store)
        identity = Identity(
            id=uuid4(),
            self_description="I learn.",
            principles=[Principle(statement="Always be honest.", source="session_1")],
            open_questions=[OpenQuestion(question="What is the right tradeoff here?")],
        )
        doc = service.create_narrative(identity)
        assert "Always be honest" in doc.core_layer.content
        assert "What is the right tradeoff" in doc.core_layer.content


def test_generate_recent_layer_negative_emotional_tone():
    """_generate_recent_layer_from_eigenstate handles negative emotional tone."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = NarrativeService(store)
        identity = Identity(id=uuid4())
        service.create_narrative(identity)
        eigenstate = Eigenstate(
            session_id=uuid4(),
            session_summary="A difficult session.",
            key_insight="Pressure reveals drift.",
            emotional_tone=-0.5,
            open_threads=["Need to revisit values"],
        )
        updated = service.update_from_identity_and_eigenstate(identity, eigenstate)
        assert "negative" in updated.recent_layer.content.lower()
        assert "Pressure reveals drift" in updated.recent_layer.content


def test_sync_threads_updates_existing_active_thread():
    """_sync_threads_from_eigenstate updates last_updated on an existing active thread."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = NarrativeService(store)
        identity = Identity(id=uuid4())
        service.create_narrative(identity)

        eigenstate_1 = Eigenstate(
            session_id=uuid4(),
            session_summary="Session 1.",
            open_threads=["Finish the tests"],
        )
        updated_1 = service.update_from_identity_and_eigenstate(identity, eigenstate_1)
        assert any("tests" in t.title.lower() for t in updated_1.threads)

        eigenstate_2 = Eigenstate(
            session_id=uuid4(),
            session_summary="Session 2.",
            open_threads=["Finish the tests"],
        )
        updated_2 = service.update_from_identity_and_eigenstate(identity, eigenstate_2)
        threads_with_tests = [t for t in updated_2.threads if "tests" in t.title.lower()]
        assert len(threads_with_tests) == 1


def test_validate_narrative_file_nonexistent_path():
    """validate_narrative_file returns False when file does not exist."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = NarrativeService(store)
        nonexistent = Path(tmpdir) / "no_such_file.md"
        is_valid, issues = service.validate_narrative_file(nonexistent)
        assert not is_valid
        assert issues == ["File does not exist"]


def test_validate_narrative_file_missing_core_layer():
    """validate_narrative_file reports CORE LAYER missing when not in file."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = NarrativeService(store)
        narrative_path = Path(tmpdir) / "NARRATIVE.md"
        narrative_path.write_text("## RECENT LAYER\n\nI just did something.\n", encoding="utf-8")
        is_valid, issues = service.validate_narrative_file(narrative_path)
        assert not is_valid
        assert any("CORE LAYER" in issue for issue in issues)


def test_generate_core_layer_includes_core_values():
    """create_narrative generates core values section from identity."""
    from atman.core.models.identity import CoreValue

    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = NarrativeService(store)
        identity = Identity(
            id=uuid4(),
            self_description="I value honesty.",
            core_values=[
                CoreValue(name="honesty", description="Always tell the truth.", confidence=0.9)
            ],
        )
        doc = service.create_narrative(identity)
        assert "honesty" in doc.core_layer.content.lower()
        assert "Always tell the truth" in doc.core_layer.content
