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
