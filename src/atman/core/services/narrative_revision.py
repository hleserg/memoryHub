"""
Narrative Revision Service.

This service handles narrative document updates during reflection.
It's part of deep reflection but can be used independently.
"""

import warnings
from datetime import UTC, datetime
from typing import ClassVar
from uuid import UUID

from atman.core.clock_impl import SystemClock
from atman.core.exceptions import GovernanceRejectedError
from atman.core.models.experience import SessionExperience
from atman.core.models.governance import GovernanceDecision
from atman.core.models.identity import Identity
from atman.core.models.narrative import LayerType, NarrativeDocument, NarrativeThread
from atman.core.models.reflection import PatternCandidate, ReflectionLevel
from atman.core.models.self_applied_change import (
    SelfAppliedChange,
    SelfChangeSource,
    SelfChangeTargetKind,
)
from atman.core.ports.clock import ClockPort
from atman.core.ports.reflection import (
    NarrativeRepository,
    NarrativeWriteAuditPort,
    ReflectionModel,
)
from atman.core.ports.self_applied_changes import SelfAppliedChangeStore


class NarrativeRevisionService:
    """
    Service for revising narrative documents during reflection.

    Handles:
    - Core layer updates (rare, fundamental changes)
    - Recent layer updates (frequent, session-by-session)
    - Thread management (opening, updating, closing)

    All commits go through optimistic concurrency on ``updated_at`` and emit
    audit signals via ``narrative_audit``. Callers must pass a real governance
    sink or explicitly :class:`~atman.core.narrative_write_audit.NoOpNarrativeWriteAudit`
    for tests/demos — there is no silent ``None`` default.
    """

    def __init__(
        self,
        narrative_repo: NarrativeRepository,
        reflection_model: ReflectionModel,
        *,
        narrative_audit: NarrativeWriteAuditPort,
        clock: ClockPort | None = None,
        self_applied_change_store: SelfAppliedChangeStore | None = None,
    ):
        """Initialize narrative revision service.

        ``self_applied_change_store`` is required only when
        :meth:`apply_self_layer_update` or :meth:`revert_self_change` are used.
        """
        self.narrative_repo = narrative_repo
        self.reflection_model = reflection_model
        self._narrative_audit = narrative_audit
        self._clock = clock or SystemClock()
        self._self_applied_change_store = self_applied_change_store

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
        try:
            self._narrative_audit.record_narrative_commit(
                change_kind=change_kind,
                narrative_id=draft.id,
                identity_id=draft.identity_id,
                reason_or_summary=audit_summary,
            )
        except Exception as exc:
            try:
                self._narrative_audit.record_narrative_commit_audit_failure(
                    change_kind=change_kind,
                    narrative_id=draft.id,
                    identity_id=draft.identity_id,
                    committed_summary=audit_summary,
                    error_message=f"{type(exc).__name__}: {exc}",
                )
            except Exception as nested:
                warnings.warn(
                    "Narrative persisted but audit failed; "
                    f"failure recorder also raised: {nested!r}",
                    RuntimeWarning,
                    stacklevel=2,
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

        proposed = self.reflection_model.propose_narrative_update(
            current_narrative=draft,
            recent_experiences=experiences,
            reflection_level=reflection_level,
        )
        proposed_update = proposed.body

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
        governance: GovernanceDecision,
    ) -> str:
        """
        Update the core narrative layer.

        This should only happen during deep reflection when fundamental
        changes to self-understanding occur.

        Args:
            identity: Current identity
            patterns: Patterns that triggered this update
            reason: Reason for core layer update
            governance: Required governance decision; core writes are never AUTO

        Returns:
            New content for core layer

        Raises:
            GovernanceRejectedError: If governance does not allow a core commit
            NarrativePersistenceConflictError: If the repository rejects the
                write because ``updated_at`` no longer matches the snapshot
                taken at read time.
        """
        if not governance.allows_core_narrative_commit():
            raise GovernanceRejectedError(
                "Core narrative commit requires an explicit governance approval "
                f"(mode={governance.mode.value}, review_approved={governance.review_approved})"
            )

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
                thread.last_updated = self._clock.now()

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

    # ------------------------------------------------------------------
    # Self-apply API (reflection-initiated layer rewrites, audit + revert)
    # ------------------------------------------------------------------

    _LAYER_TARGET_KIND: ClassVar[dict[LayerType, SelfChangeTargetKind]] = {
        LayerType.CORE: SelfChangeTargetKind.NARRATIVE_CORE_LAYER,
        LayerType.RECENT: SelfChangeTargetKind.NARRATIVE_RECENT_LAYER,
    }

    def apply_self_layer_update(
        self,
        layer: LayerType,
        new_content: str,
        source: SelfChangeSource,
    ) -> SelfAppliedChange:
        """
        Apply a narrative layer rewrite initiated by reflection itself.

        Unlike :meth:`update_core_layer` this path does **not** require a
        :class:`GovernanceDecision` — reflection is allowed to revise its own
        narrative — but the source must carry rationale, confidence statement,
        and supporting moment ids (enforced by ``SelfChangeSource``).

        Args:
            layer: ``LayerType.CORE`` or ``LayerType.RECENT``. ``THREADS`` is
                not a layer with single content and is rejected.
            new_content: new content for the layer.
            source: provenance.

        Returns:
            SelfAppliedChange audit record.

        Raises:
            RuntimeError: if no SelfAppliedChangeStore was supplied.
            ValueError: if no narrative exists, or layer is unsupported.
        """
        if layer not in self._LAYER_TARGET_KIND:
            raise ValueError(f"apply_self_layer_update does not support layer={layer.value!r}")
        store = self._require_self_applied_store("apply_self_layer_update")

        base = self.narrative_repo.get_current()
        if not base:
            raise ValueError("No narrative document to update")

        etag = base.updated_at
        draft = base.model_copy(deep=True)
        before_content = self._layer_content(draft, layer)
        self._apply_layer_content(draft, layer, new_content)

        self._commit_narrative(
            draft,
            expected_updated_at=etag,
            change_kind=f"{layer.value}_layer_self_applied",
            audit_summary=f"self_applied:{source.actor.value}",
        )

        change = SelfAppliedChange(
            actor=source.actor,
            reflection_event_id=source.reflection_event_id,
            target_kind=self._LAYER_TARGET_KIND[layer],
            target_ref=f"narrative:{base.id}:{layer.value}",
            before_snapshot={"content": before_content, "narrative_id": str(base.id)},
            after_snapshot={"content": new_content, "narrative_id": str(base.id)},
            rationale=source.rationale,
            confidence_self_assessment=source.confidence_self_assessment,
            based_on_moment_ids=list(source.based_on_moment_ids),
        )
        store.save(change)
        return change

    def revert_self_change(self, self_applied_id: UUID, reason: str) -> SelfAppliedChange:
        """
        Revert a previously self-applied narrative layer change.

        Restores ``before_snapshot.content`` to the corresponding layer and
        marks the audit row reverted. The original IdentitySnapshot/Narrative
        history rows are not modified.

        Raises:
            RuntimeError: if no SelfAppliedChangeStore.
            KeyError: if the change does not exist.
            ValueError: if not a narrative kind, already reverted, narrative
                missing, or before_snapshot malformed.
        """
        if not reason or not reason.strip():
            raise ValueError("reason must be non-empty")

        store = self._require_self_applied_store("revert_self_change")
        change = store.get(self_applied_id)
        if change is None:
            raise KeyError(f"self_applied_change {self_applied_id} not found")
        if change.reverted_at is not None:
            raise ValueError(f"self_applied_change {self_applied_id} already reverted")

        layer = self._layer_for_target_kind(change.target_kind)

        before_content = change.before_snapshot.get("content")
        if not isinstance(before_content, str):
            raise ValueError(f"self_applied_change {self_applied_id} has malformed before_snapshot")

        base = self.narrative_repo.get_current()
        if not base:
            raise ValueError("No narrative document to revert against")

        etag = base.updated_at
        draft = base.model_copy(deep=True)
        self._apply_layer_content(draft, layer, before_content)

        self._commit_narrative(
            draft,
            expected_updated_at=etag,
            change_kind=f"{layer.value}_layer_self_reverted",
            audit_summary=f"revert:{self_applied_id}",
        )

        return store.mark_reverted(
            self_applied_id,
            reverted_at=datetime.now(UTC),
            reason=reason.strip(),
        )

    # ----- helpers -----

    def _require_self_applied_store(self, method: str) -> SelfAppliedChangeStore:
        if self._self_applied_change_store is None:
            raise RuntimeError(
                f"NarrativeRevisionService.{method} requires a SelfAppliedChangeStore; "
                "pass one to the constructor"
            )
        return self._self_applied_change_store

    @staticmethod
    def _layer_content(doc: NarrativeDocument, layer: LayerType) -> str:
        if layer == LayerType.CORE:
            return doc.core_layer.content
        return doc.recent_layer.content

    @staticmethod
    def _apply_layer_content(doc: NarrativeDocument, layer: LayerType, content: str) -> None:
        if layer == LayerType.CORE:
            doc.update_core_layer(content)
        else:
            doc.update_recent_layer(content)

    @classmethod
    def _layer_for_target_kind(cls, kind: SelfChangeTargetKind) -> LayerType:
        for layer, mapped in cls._LAYER_TARGET_KIND.items():
            if mapped == kind:
                return layer
        raise ValueError(
            f"revert_self_change does not handle target_kind={kind.value!r}; "
            "identity kinds go through IdentityService.revert_self_change"
        )

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
