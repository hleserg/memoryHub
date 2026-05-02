"""
Narrative Service - manages self-narrative lifecycle.

Responsibilities:
- Create and update narrative documents
- Manage three-layer structure (CORE, RECENT, THREADS)
- Archive old narratives before replacement
- Validate first-person style
- Render narrative as markdown
"""

import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from atman.core.models import (
    Eigenstate,
    Identity,
    LayerType,
    NarrativeDocument,
    NarrativeLayer,
    NarrativeThread,
)
from atman.core.ports.state_store import StateStore


class NarrativeService:
    """
    Service for managing self-narrative documents.

    The narrative is a "letter to self" read at session start.
    It has three layers:
    - CORE: Stable identity and fundamental understanding
    - RECENT: What happened recently, updated frequently
    - THREADS: Ongoing storylines
    """

    def __init__(self, state_store: StateStore):
        """
        Initialize narrative service.

        Args:
            state_store: StateStore implementation for persistence
        """
        self.state_store = state_store

    def create_narrative(self, identity: Identity) -> NarrativeDocument:
        """
        Create initial narrative from identity.

        Args:
            identity: Identity to create narrative for

        Returns:
            NarrativeDocument: Newly created narrative
        """
        # Create core layer from identity
        core_content = self._generate_core_layer_from_identity(identity)

        narrative = NarrativeDocument(
            identity_id=identity.id,
            core_layer=NarrativeLayer(
                layer_type=LayerType.CORE,
                content=core_content,
            ),
            recent_layer=NarrativeLayer(
                layer_type=LayerType.RECENT,
                content="I have just begun. No recent experiences yet to reflect upon.",
            ),
            threads=[],
        )

        return self.state_store.save_narrative(narrative)

    def get_narrative(self, identity_id: UUID) -> NarrativeDocument | None:
        """
        Get current narrative for an identity.

        Args:
            identity_id: UUID of the identity

        Returns:
            NarrativeDocument | None: Current narrative if exists, None otherwise
        """
        return self.state_store.load_narrative(identity_id)

    def update_from_identity_and_eigenstate(
        self, identity: Identity, eigenstate: Eigenstate | None = None
    ) -> NarrativeDocument:
        """
        Update narrative from current identity and eigenstate.

        This is the main update method called after sessions.

        Args:
            identity: Current identity
            eigenstate: Optional eigenstate from session end

        Returns:
            NarrativeDocument: Updated narrative
        """
        narrative = self.state_store.load_narrative(identity.id)

        if narrative is None:
            # Create new narrative if none exists
            return self.create_narrative(identity)

        # Archive old narrative before major update
        if eigenstate is not None and eigenstate.session_summary:
            self.state_store.archive_narrative(
                narrative.id, f"Session {eigenstate.session_id} completed"
            )

        # Update core layer if identity changed significantly
        core_content = self._generate_core_layer_from_identity(identity)
        if core_content != narrative.core_layer.content:
            narrative.update_core_layer(core_content)

        # Update recent layer from eigenstate
        if eigenstate is not None:
            recent_content = self._generate_recent_layer_from_eigenstate(eigenstate)
            narrative.update_recent_layer(recent_content)

            # Update threads based on eigenstate open threads
            self._sync_threads_from_eigenstate(narrative, eigenstate)

        return self.state_store.save_narrative(narrative)

    def update_recent_layer(self, identity_id: UUID, content: str) -> NarrativeDocument:
        """
        Update only the recent layer.

        Args:
            identity_id: UUID of the identity
            content: New recent layer content (must be first-person)

        Returns:
            NarrativeDocument: Updated narrative

        Raises:
            ValueError: If narrative not found or content not first-person
        """
        narrative = self.state_store.load_narrative(identity_id)
        if narrative is None:
            raise ValueError(f"Narrative for identity {identity_id} not found")

        # Validate first-person style
        self._validate_first_person(content)

        narrative.update_recent_layer(content)
        return self.state_store.save_narrative(narrative)

    def update_core_layer(self, identity_id: UUID, content: str) -> NarrativeDocument:
        """
        Update the core layer.

        This should be done rarely - only for fundamental shifts.

        Args:
            identity_id: UUID of the identity
            content: New core layer content (must be first-person)

        Returns:
            NarrativeDocument: Updated narrative

        Raises:
            ValueError: If narrative not found or content not first-person
        """
        narrative = self.state_store.load_narrative(identity_id)
        if narrative is None:
            raise ValueError(f"Narrative for identity {identity_id} not found")

        # Validate first-person style
        self._validate_first_person(content)

        # Archive before core change
        self.state_store.archive_narrative(narrative.id, "Core layer update")

        narrative.update_core_layer(content)
        return self.state_store.save_narrative(narrative)

    def add_thread(self, identity_id: UUID, thread: NarrativeThread) -> NarrativeDocument:
        """
        Add a new narrative thread.

        Args:
            identity_id: UUID of the identity
            thread: Thread to add

        Returns:
            NarrativeDocument: Updated narrative

        Raises:
            ValueError: If narrative not found
        """
        narrative = self.state_store.load_narrative(identity_id)
        if narrative is None:
            raise ValueError(f"Narrative for identity {identity_id} not found")

        narrative.add_thread(thread)
        return self.state_store.save_narrative(narrative)

    def close_thread(self, identity_id: UUID, thread_id: UUID, reason: str) -> NarrativeDocument:
        """
        Close a narrative thread with explicit reason.

        Threads don't just disappear - they must be explicitly closed.

        Args:
            identity_id: UUID of the identity
            thread_id: UUID of the thread to close
            reason: Reason for closing (required)

        Returns:
            NarrativeDocument: Updated narrative

        Raises:
            ValueError: If narrative not found, thread not found, or reason empty
        """
        if not reason or not reason.strip():
            raise ValueError("closure_reason is required when closing a thread")

        narrative = self.state_store.load_narrative(identity_id)
        if narrative is None:
            raise ValueError(f"Narrative for identity {identity_id} not found")

        narrative.close_thread(thread_id, reason)
        return self.state_store.save_narrative(narrative)

    def render_to_file(self, identity_id: UUID, output_path: Path) -> Path:
        """
        Render narrative to NARRATIVE.md file.

        Args:
            identity_id: UUID of the identity
            output_path: Path to write NARRATIVE.md

        Returns:
            Path: Path where file was written

        Raises:
            ValueError: If narrative not found
        """
        narrative = self.state_store.load_narrative(identity_id)
        if narrative is None:
            raise ValueError(f"Narrative for identity {identity_id} not found")

        markdown = narrative.render_markdown()
        output_path.write_text(markdown, encoding="utf-8")

        return output_path

    def validate_narrative_file(self, narrative_path: Path) -> tuple[bool, list[str]]:
        """
        Validate a NARRATIVE.md file.

        Checks:
        - File exists and is readable
        - Contains mandatory sections (CORE LAYER, RECENT LAYER)
        - Is written in first person (no "the agent", "atman did", etc.)

        Args:
            narrative_path: Path to NARRATIVE.md file

        Returns:
            tuple[bool, list[str]]: (is_valid, list of issues)
        """
        issues: list[str] = []

        # Check file exists
        if not narrative_path.exists():
            return False, ["File does not exist"]

        try:
            content = narrative_path.read_text(encoding="utf-8")
        except Exception as e:
            return False, [f"Cannot read file: {e}"]

        # Check for mandatory sections
        if "## CORE LAYER" not in content:
            issues.append("Missing mandatory section: CORE LAYER")

        if "## RECENT LAYER" not in content:
            issues.append("Missing mandatory section: RECENT LAYER")

        # Check for third-person phrases
        third_person_issues = self._check_third_person(content)
        issues.extend(third_person_issues)

        return len(issues) == 0, issues

    def _generate_core_layer_from_identity(self, identity: Identity) -> str:
        """Generate core layer content from identity."""
        lines = []

        # Self-description
        if identity.self_description:
            lines.append(identity.self_description)
            lines.append("")

        # Core values
        if identity.core_values:
            lines.append("**My core values:**")
            lines.append("")
            for value in identity.core_values:
                lines.append(f"- **{value.name}**: {value.description}")
            lines.append("")

        # Principles
        if identity.principles:
            lines.append("**My principles:**")
            lines.append("")
            for principle in identity.principles:
                lines.append(f"- {principle.statement}")
            lines.append("")

        # Open questions
        if identity.open_questions:
            lines.append("**Questions I'm holding:**")
            lines.append("")
            for question in identity.open_questions:
                lines.append(f"- {question.question}")
            lines.append("")

        return "\n".join(lines).strip()

    def _generate_recent_layer_from_eigenstate(self, eigenstate: Eigenstate) -> str:
        """Generate recent layer content from eigenstate."""
        lines = []

        # Session summary
        if eigenstate.session_summary:
            lines.append(eigenstate.session_summary)
            lines.append("")

        # Key insight
        if eigenstate.key_insight:
            lines.append(f"**Key insight:** {eigenstate.key_insight}")
            lines.append("")

        # Open threads
        if eigenstate.open_threads:
            lines.append("**What I left open:**")
            lines.append("")
            for thread in eigenstate.open_threads:
                lines.append(f"- {thread}")
            lines.append("")

        # Emotional state
        tone_desc = (
            "positive"
            if eigenstate.emotional_tone > 0.2
            else "negative"
            if eigenstate.emotional_tone < -0.2
            else "neutral"
        )
        lines.append(
            f"I'm ending this session with a {tone_desc} tone "
            f"(valence: {eigenstate.emotional_tone:.2f})."
        )

        return "\n".join(lines).strip()

    def _sync_threads_from_eigenstate(
        self, narrative: NarrativeDocument, eigenstate: Eigenstate
    ) -> None:
        """Update narrative threads based on eigenstate open threads."""
        # For each open thread in eigenstate, ensure there's a narrative thread
        for open_thread in eigenstate.open_threads:
            # Check if thread already exists
            existing = False
            for thread in narrative.threads:
                if thread.is_active and open_thread.lower() in thread.title.lower():
                    # Update existing thread
                    thread.last_updated = datetime.now(UTC)
                    thread.current_state = f"Still active as of session {eigenstate.session_id}"
                    existing = True
                    break

            # Create new thread if doesn't exist
            if not existing:
                new_thread = NarrativeThread(
                    title=open_thread,
                    description=f"Emerged during session {eigenstate.session_id}",
                    current_state="Newly opened",
                )
                narrative.add_thread(new_thread)

    def _validate_first_person(self, content: str) -> None:
        """
        Validate that content is in first person.

        Raises:
            ValueError: If content contains third-person phrases
        """
        issues = self._check_third_person(content)
        if issues:
            raise ValueError(f"Content not in first person: {'; '.join(issues)}")

    def _check_third_person(self, content: str) -> list[str]:
        """Check for third-person phrases in content."""
        issues: list[str] = []
        content_lower = content.lower()

        forbidden_phrases = [
            (r"\bthe agent\b", "Found 'the agent' (should be 'I')"),
            (r"\batman did\b", "Found 'atman did' (should be 'I did')"),
            (r"\batman made\b", "Found 'atman made' (should be 'I made')"),
            (r"\batman decided\b", "Found 'atman decided' (should be 'I decided')"),
            (r"\bthe system\b", "Found 'the system' (avoid third-person references)"),
            (r"\bhe/she\b", "Found 'he/she' (should be 'I')"),
        ]

        for pattern, message in forbidden_phrases:
            if re.search(pattern, content_lower):
                issues.append(message)

        return issues
