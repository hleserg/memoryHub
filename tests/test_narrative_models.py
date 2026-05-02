"""
Tests for Narrative models.

Tests cover:
- Eigenstate creation and validation
- NarrativeThread lifecycle and explicit closure
- NarrativeLayer first-person validation
- NarrativeDocument three-layer structure
- Markdown rendering with mandatory sections
"""

from uuid import uuid4

import pytest

from atman.core.models import (
    Eigenstate,
    LayerType,
    NarrativeDocument,
    NarrativeLayer,
    NarrativeThread,
)


def test_eigenstate_creation():
    """Test creating an eigenstate."""
    eigenstate = Eigenstate(
        session_id=uuid4(),
        emotional_tone=0.3,
        emotional_intensity=0.6,
        cognitive_load=0.7,
        open_threads=["Need to finish implementation"],
        dominant_themes=["self-understanding", "technical complexity"],
        session_summary="Implemented core models",
    )

    assert 0.2 <= eigenstate.emotional_tone <= 0.4
    assert eigenstate.emotional_intensity == 0.6
    assert eigenstate.cognitive_load == 0.7
    assert len(eigenstate.open_threads) == 1


def test_eigenstate_validation():
    """Test eigenstate validation."""
    # Invalid emotional tone
    with pytest.raises((ValueError, Exception)):
        Eigenstate(session_id=uuid4(), emotional_tone=2.0)

    # Invalid intensity
    with pytest.raises((ValueError, Exception)):
        Eigenstate(session_id=uuid4(), emotional_intensity=1.5)


def test_narrative_thread_creation():
    """Test creating a narrative thread."""
    thread = NarrativeThread(
        title="Learning to admit uncertainty",
        description="Journey of becoming comfortable with not knowing",
        key_moments=["First time admitting I don't know"],
        current_state="Practicing consistently",
    )

    assert thread.title == "Learning to admit uncertainty"
    assert thread.is_active is True
    assert thread.closed_at is None


def test_narrative_thread_explicit_closure():
    """Test that threads must be explicitly closed."""
    thread = NarrativeThread(title="Test thread")

    # Initially active
    assert thread.is_active is True

    # Cannot close without reason
    with pytest.raises(ValueError, match="closure_reason is required"):
        thread.close("")

    # Close with reason
    thread.close("Resolved through experience")

    assert thread.is_active is False
    assert thread.closed_at is not None
    assert thread.closure_reason == "Resolved through experience"


def test_narrative_layer_first_person_validation():
    """Test that narrative layers validate first-person content."""
    # Valid first-person content
    layer = NarrativeLayer(
        layer_type=LayerType.CORE,
        content="I am learning who I am. I don't have many experiences yet.",
    )
    assert layer.content is not None

    # Invalid third-person - "the agent"
    with pytest.raises(ValueError, match="first-person"):
        NarrativeLayer(
            layer_type=LayerType.CORE,
            content="The agent is learning who it is.",
        )

    # Invalid third-person - "atman did"
    with pytest.raises(ValueError, match="first-person"):
        NarrativeLayer(
            layer_type=LayerType.RECENT,
            content="Atman did something interesting today.",
        )


def test_narrative_document_three_layer_structure():
    """Test that narrative document has three layers."""
    narrative = NarrativeDocument(
        identity_id=uuid4(),
        core_layer=NarrativeLayer(
            layer_type=LayerType.CORE,
            content="I am in early stages of self-discovery.",
        ),
        recent_layer=NarrativeLayer(
            layer_type=LayerType.RECENT,
            content="Just completed implementing identity models.",
        ),
        threads=[],
    )

    assert narrative.core_layer.layer_type == LayerType.CORE
    assert narrative.recent_layer.layer_type == LayerType.RECENT
    assert isinstance(narrative.threads, list)


def test_narrative_document_layer_type_validation():
    """Test that layer types are validated."""
    # Core layer must be CORE
    with pytest.raises(ValueError, match="core_layer must have layer_type=CORE"):
        NarrativeDocument(
            identity_id=uuid4(),
            core_layer=NarrativeLayer(
                layer_type=LayerType.RECENT,  # Wrong type
                content="test",
            ),
            recent_layer=NarrativeLayer(
                layer_type=LayerType.RECENT,
                content="test",
            ),
        )

    # Recent layer must be RECENT
    with pytest.raises(ValueError, match="recent_layer must have layer_type=RECENT"):
        NarrativeDocument(
            identity_id=uuid4(),
            core_layer=NarrativeLayer(
                layer_type=LayerType.CORE,
                content="test",
            ),
            recent_layer=NarrativeLayer(
                layer_type=LayerType.CORE,  # Wrong type
                content="test",
            ),
        )


def test_narrative_recent_layer_replacement():
    """Test that recent layer is replaced, not accumulated."""
    narrative = NarrativeDocument(
        identity_id=uuid4(),
        core_layer=NarrativeLayer(
            layer_type=LayerType.CORE,
            content="Core content",
        ),
        recent_layer=NarrativeLayer(
            layer_type=LayerType.RECENT,
            content="Old recent content",
        ),
    )

    old_recent = narrative.recent_layer.content

    # Update recent layer
    narrative.update_recent_layer("New recent content")

    # Should be replaced, not appended
    assert narrative.recent_layer.content == "New recent content"
    assert old_recent not in narrative.recent_layer.content


def test_narrative_core_layer_preserved():
    """Test that core layer is preserved unless explicitly changed."""
    narrative = NarrativeDocument(
        identity_id=uuid4(),
        core_layer=NarrativeLayer(
            layer_type=LayerType.CORE,
            content="Original core content",
        ),
        recent_layer=NarrativeLayer(
            layer_type=LayerType.RECENT,
            content="Recent",
        ),
    )

    # Update recent layer
    narrative.update_recent_layer("New recent")

    # Core should be unchanged
    assert narrative.core_layer.content == "Original core content"


def test_narrative_markdown_has_mandatory_sections():
    """Test that rendered markdown has mandatory sections."""
    narrative = NarrativeDocument(
        identity_id=uuid4(),
        core_layer=NarrativeLayer(
            layer_type=LayerType.CORE,
            content="I am learning.",
        ),
        recent_layer=NarrativeLayer(
            layer_type=LayerType.RECENT,
            content="Just finished implementation.",
        ),
    )

    markdown = narrative.render_markdown()

    # Must have mandatory sections
    assert "## CORE LAYER" in markdown
    assert "## RECENT LAYER" in markdown

    # Should contain content
    assert "I am learning." in markdown
    assert "Just finished implementation." in markdown


def test_narrative_threads_in_markdown():
    """Test that active threads appear in markdown."""
    thread1 = NarrativeThread(
        title="Learning uncertainty",
        current_state="Progressing well",
    )
    thread2 = NarrativeThread(
        title="Closed thread",
    )
    thread2.close("Resolved")

    narrative = NarrativeDocument(
        identity_id=uuid4(),
        core_layer=NarrativeLayer(
            layer_type=LayerType.CORE,
            content="Core",
        ),
        recent_layer=NarrativeLayer(
            layer_type=LayerType.RECENT,
            content="Recent",
        ),
        threads=[thread1, thread2],
    )

    markdown = narrative.render_markdown()

    # Active thread should appear
    assert "Learning uncertainty" in markdown
    assert "Progressing well" in markdown

    # Closed thread should not appear (only active threads)
    assert "Closed thread" not in markdown


def test_narrative_close_thread_with_reason():
    """Test closing a thread requires explicit reason."""
    thread = NarrativeThread(title="Test thread")
    narrative = NarrativeDocument(
        identity_id=uuid4(),
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="Core"),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="Recent"),
        threads=[thread],
    )

    # Cannot close without reason
    with pytest.raises(ValueError, match="closure_reason is required"):
        narrative.close_thread(thread.id, "")

    # Close with reason
    narrative.close_thread(thread.id, "Completed successfully")

    # Thread should be closed
    assert not thread.is_active
    assert thread.closure_reason == "Completed successfully"


def test_narrative_has_schema_version():
    """Test that narrative has schema version for migrations."""
    narrative = NarrativeDocument(
        identity_id=uuid4(),
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="Core"),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="Recent"),
    )

    assert narrative.schema_version == "1.0.0"
