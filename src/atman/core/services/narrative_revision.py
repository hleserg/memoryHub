"""
Narrative Revision Service.

This service handles narrative document updates during reflection.
It's part of deep reflection but can be used independently.
"""

from datetime import UTC, datetime
from uuid import UUID

from atman.core.models.experience import SessionExperience
from atman.core.models.identity import Identity
from atman.core.models.narrative import NarrativeDocument, NarrativeThread
from atman.core.models.reflection import PatternCandidate, ReflectionLevel
from atman.core.ports.reflection import (
    NarrativeRepository,
    NarrativeWriteAuditPort,
    ReflectionModel,
)


class NarrativeRevisionService:
    """
    Service for revising narrative documents during reflection.

    Handles:
    - Core layer updates (rare, fundamental changes)
    - Recent layer updates (frequent, session-by-session)
    - Thread management (opening, updating, closing)

    All commits go through optimistic concurrency on ``updated_at`` and may
    emit audit records when a :class:`NarrativeWriteAuditPort` is configured.
    """

    def __init__(
        self,
        narrative_repo: NarrativeRepository,
        reflection_model: ReflectionModel,
        *,
        narrative_audit: NarrativeWriteAuditPort | None = None,
    ):
        """Initialize narrative revision service."""
        self.narrative_repo = narrative_repo
        self.reflection_model = reflection_model
        self._narrative_audit = narrative_audit

    def _commit_narrative(
        self,
        draft: NarrativeDocument,
        *,
        expected_updated_at: datetime,
        change_kind: str,
        audit_summary: str,
    ) -> None:
        """Persist draft if ``expected_updated_at`` matches last commit; then audit."""
        self.narrative_repo.update(draft, expected_updated_at=expected_updated_at)
        if self._narrative_audit is not None:
            self._narrative_audit.record_narrative_commit(
                change_kind=change_kind,
                narrative_id=draft.id,
                identity_id=draft.identity_id,
                reason_or_summary=audit_summary,
            )

    def update_recent_layer(
        self, experiences: list[SessionExperience], reflection_level: ReflectionLevel
    ) -> str:
        """
        Update the recent narrative layer with new experiences.

        Args:
            experiences: Recent experiences to incorporate
            reflection_level: Level of reflection performing the update

        Returns:
            New content for recent layer
        """
        base = self.narrative_repo.get_current()
        if not base:
            return "No narrative to update"

        etag = base.updated_at
        draft = base.model_copy(deep=True)

        proposed_update = self.reflection_model.propose_narrative_update(
            current_narrative=draft,
            recent_experiences=experiences,
            reflection_level=reflection_level,
        )

        draft.update_recent_layer(proposed_update)
        self._commit_narrative(
            draft,
            expected_updated_at=etag,
            change_kind="recent_layer",
            audit_summary=f"recent_layer:{reflection_level.value}",
        )

        return proposed_update

    def update_core_layer(
        self,
        identity: Identity,
        patterns: list[PatternCandidate],
        reason: str,
    ) -> str:
        """
        Update the core narrative layer.

        This should only happen during deep reflection when fundamental
        changes to self-understanding occur.

        Args:
            identity: Current identity
            patterns: Patterns that triggered this update
            reason: Reason for core layer update

        Returns:
            New content for core layer

        Raises:
            NarrativePersistenceConflictError: If the repository rejects the
                write because ``updated_at`` no longer matches the snapshot
                taken at read time.
        """
        base = self.narrative_repo.get_current()
        if not base:
            return "No narrative to update"

        etag = base.updated_at
        draft = base.model_copy(deep=True)

        new_core_content = self._generate_core_content(identity, patterns, reason)

        draft.update_core_layer(new_core_content)
        self._commit_narrative(
            draft,
            expected_updated_at=etag,
            change_kind="core_layer",
            audit_summary=reason,
        )

        return new_core_content

    def open_thread(self, title: str, description: str, context: str = "") -> NarrativeThread:
        """
        Open a new narrative thread.

        Threads track ongoing storylines across sessions.

        Args:
            title: Brief title of the thread
            description: What this thread is about
            context: Additional context

        Returns:
            The created thread
        """
        base = self.narrative_repo.get_current()
        if not base:
            raise ValueError("No narrative document to add thread to")

        etag = base.updated_at
        draft = base.model_copy(deep=True)

        thread = NarrativeThread(
            title=title,
            description=description,
            current_state=context if context else "Just started",
        )

        draft.add_thread(thread)
        self._commit_narrative(
            draft,
            expected_updated_at=etag,
            change_kind="thread_open",
            audit_summary=title,
        )

        return thread

    def update_thread(
        self, thread_id: str, new_state: str, add_moment: str = ""
    ) -> NarrativeThread | None:
        """
        Update an existing narrative thread.

        Args:
            thread_id: ID of thread to update
            new_state: New current state
            add_moment: Optional moment to add to thread

        Returns:
            Updated thread or None if not found
        """
        base = self.narrative_repo.get_current()
        if not base:
            return None

        try:
            thread_uuid = UUID(thread_id)
        except ValueError:
            return None

        etag = base.updated_at
        draft = base.model_copy(deep=True)

        for thread in draft.threads:
            if thread.id == thread_uuid:
                thread.current_state = new_state
                thread.last_updated = datetime.now(UTC)

                if add_moment:
                    thread.key_moments.append(add_moment)

                self._commit_narrative(
                    draft,
                    expected_updated_at=etag,
                    change_kind="thread_update",
                    audit_summary=f"thread:{thread_uuid}",
                )
                return thread

        return None

    def close_thread(self, thread_id: str, reason: str) -> bool:
        """
        Close a narrative thread.

        Threads must be explicitly closed - they don't just disappear.

        Args:
            thread_id: ID of thread to close
            reason: Why this thread is being closed

        Returns:
            True if closed successfully, False if thread not found
        """
        base = self.narrative_repo.get_current()
        if not base:
            return False

        try:
            thread_uuid = UUID(thread_id)
        except ValueError:
            return False

        etag = base.updated_at
        draft = base.model_copy(deep=True)

        try:
            draft.close_thread(thread_uuid, reason)
        except ValueError:
            return False

        self._commit_narrative(
            draft,
            expected_updated_at=etag,
            change_kind="thread_close",
            audit_summary=reason,
        )
        return True

    def _generate_core_content(
        self, identity: Identity, patterns: list[PatternCandidate], reason: str
    ) -> str:
        """Generate new core narrative content."""
        parts = []

        if identity.self_description:
            parts.append(identity.self_description)

        if identity.core_values:
            values_list = ", ".join(v.name for v in identity.core_values)
            parts.append(f"I value: {values_list}.")

        if identity.principles:
            principles_list = "; ".join(p.statement for p in identity.principles[:3])
            parts.append(f"I believe: {principles_list}.")

        if patterns:
            pattern_insights = " ".join(p.description for p in patterns if p.confidence > 0.7)
            if pattern_insights:
                parts.append(f"I'm learning that: {pattern_insights}")

        parts.append(f"Updated because: {reason}")

        return " ".join(parts)
