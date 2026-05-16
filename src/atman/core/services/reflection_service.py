"""
Reflection services for the Reflection Engine.

These services implement the three levels of reflection:
- MicroReflectionService: After-session reflection
- DailyReflectionService: End-of-day pattern detection
- DeepReflectionService: Scheduled deep reflection with health assessment
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, time
from typing import Literal
from uuid import UUID

from atman.core.clock_impl import SystemClock, ensure_utc
from atman.core.exceptions import NarrativePersistenceConflictError
from atman.core.models.experience import ReframingNote, ReframingNoteAppendResult, SessionExperience
from atman.core.models.identity import Identity
from atman.core.models.reflection import (
    CriterionAssessment,
    HealthAssessment,
    JahodaCriterion,
    PatternCandidate,
    PatternType,
    ReflectionEvent,
    ReflectionLevel,
)
from atman.core.models.reflection_request import ReflectionRequest, ReflectionRequestLevel
from atman.core.ports.clock import ClockPort
from atman.core.ports.reflection import (
    HealthAssessmentStore,
    IdentityRepository,
    NarrativeRepository,
    PatternStore,
    ReflectionEventPersistenceObserver,
    ReflectionEventStore,
    ReflectionModel,
)
from atman.core.ports.reflection_request_queue import ReflectionRequestQueue
from atman.core.ports.session_repository import SessionRepository
from atman.core.reflection_event_audit import NoOpReflectionEventPersistenceObserver
from atman.core.reflection_run_keys import (
    daily_pattern_detection_key,
    daily_reflection_run_key_empty_day,
    daily_reflection_run_key_for_identity,
    daily_reflection_run_key_no_identity,
    deep_pattern_detection_key,
    deep_reflection_run_key_empty,
    deep_reflection_run_key_for_identity,
    deep_reflection_run_key_no_identity,
    health_assessment_id_for_run_key,
    identity_anchor_snapshot_id_for_run_key,
    reframing_trigger_key,
)
from atman.core.services.entity_relations_formulator import EntityRelationsFormulator
from atman.core.services.narrative_revision import NarrativeRevisionService
from atman.core.services.session_experience_view import build_session_experience
from atman.core.services.structured_markers_aggregator import StructuredMarkersAggregator


# PLAYBOOK-START
# id: idempotent-long-running-operations
# category: design-patterns
# title: Idempotent Long-Running Operations via Deterministic Run Keys
# status: refined
#
# Pattern: compute a deterministic run_key from the operation's input
# parameters (date + identity id + scope). Before executing side effects,
# check whether a terminal success event with this key already exists in
# the event store. If yes — return the existing result immediately. If no
# — execute, then persist the success event with outcome=*_ok / *_empty /
# *_skipped. The operation is now safe to retry, replay, and schedule
# redundantly without producing duplicate side effects.
#
# Why generalizable: any long-running job (batch processing, scheduled LLM
# calls, nightly aggregations, webhook processing) needs this. Exception-
# based "just retry" loses context; mutable "update a status flag" creates
# race conditions. Deterministic keys + terminal success events solve both
# without distributed locks or two-phase commits.
#
# Trade-offs: requires a queryable event store with run_key index; adds one
# read before every execution. Worth it whenever the operation has observable
# side effects that must not be repeated.
# PLAYBOOK-END
def _daily_run_terminal_success(notes: str) -> bool:
    return any(
        x in notes for x in ("outcome=daily_ok", "outcome=daily_empty", "outcome=daily_skipped")
    )


def _deep_run_terminal_success(notes: str) -> bool:
    return any(
        x in notes for x in ("outcome=deep_ok", "outcome=deep_empty", "outcome=deep_skipped")
    )


def _utc_calendar_day_bounds(calendar_anchor: datetime) -> tuple[datetime, datetime]:
    """Inclusive [start, end] for the UTC calendar day of ``calendar_anchor``."""
    d = ensure_utc(calendar_anchor).date()
    start = datetime.combine(d, time.min, tzinfo=UTC)
    end = datetime.combine(d, time.max, tzinfo=UTC)
    return start, end


def _take_pending_requests(
    queue: ReflectionRequestQueue | None,
    level: ReflectionRequestLevel,
) -> list[ReflectionRequest]:
    """Best-effort drain of pending agent-driven requests. Never raises."""
    if queue is None:
        return []
    try:
        return queue.take_pending(level=level)
    except Exception:
        # Queue failures must not abort the reflection job — the queue is a
        # signal, not a source of truth.
        return []


def _mark_requests_consumed(
    queue: ReflectionRequestQueue | None,
    requests: list[ReflectionRequest],
    event: ReflectionEvent,
    consumed_at: datetime,
) -> None:
    """Best-effort consume; logs of failure are out of scope here."""
    if queue is None or not requests:
        return
    for req in requests:
        with contextlib.suppress(Exception):
            queue.mark_consumed(req.id, consumed_at=consumed_at, reflection_event_id=event.id)


def _reflection_identity_anchor_snapshot_id(
    identity_repo: IdentityRepository,
    identity: Identity,
    run_key: str,
) -> UUID:
    """Return (and optionally materialize) the immutable snapshot id for this job key."""
    sid = identity_anchor_snapshot_id_for_run_key(run_key)
    existing = identity_repo.get_snapshot(sid)
    if existing is not None:
        return existing.id
    snap = identity_repo.create_snapshot(
        identity,
        "Reflection job identity anchor",
        f"run_key={run_key}",
        snapshot_id=sid,
    )
    return snap.id


class MicroReflectionService:
    """
    Micro-level reflection: after-session checkpoint.

    This runs at the end of each session and updates the **recent** narrative
    layer with a session-derived summary (optimistic concurrency on
    ``NarrativeDocument.updated_at``). Eigenstate / session checkpoint
    persistence is not part of this service yet — that remains a separate
    contract when Session Manager lands.

    Narrative writes go through :class:`NarrativeRevisionService` so commits are
    audited like other reflection paths.

    Does NOT modify identity, core narrative, or add reframing notes.
    """

    def __init__(
        self,
        session_repo: SessionRepository,
        narrative_revision: NarrativeRevisionService,
        event_store: ReflectionEventStore,
        *,
        clock: ClockPort | None = None,
        reflection_event_observer: ReflectionEventPersistenceObserver | None = None,
        skill_manager=None,  # SkillManagerPort | None — optional, avoids circular import
    ):
        """Initialize micro reflection service."""
        self.session_repo = session_repo
        self.narrative_revision = narrative_revision
        self.event_store = event_store
        self._clock = clock or SystemClock()
        self._reflection_event_observer = (
            reflection_event_observer or NoOpReflectionEventPersistenceObserver()
        )
        self._skill_manager = skill_manager

    def reflect(self, session_id: UUID, agent_id: UUID | None = None) -> ReflectionEvent:
        """
        Perform micro reflection for a session.

        Args:
            session_id: ID of the session to reflect on
            agent_id: Agent UUID, required for skill-loop processing.
                      If None, skill processing is skipped silently.

        Returns:
            ReflectionEvent recording what was done
        """
        session = self.session_repo.get_session(session_id)
        if session is None:
            return self._create_skipped_micro_event(reason="no_experiences", experience_ids=[])
        moments = self.session_repo.get_key_moments_for_session(session_id)
        experiences = [build_session_experience(session, moments)] if moments else []

        if not experiences:
            return self._create_skipped_micro_event(reason="no_experiences", experience_ids=[])

        narrative = self.narrative_revision.narrative_repo.get_current()
        if not narrative:
            return self._create_skipped_micro_event(
                reason="no_narrative",
                experience_ids=[exp.id for exp in experiences],
            )

        try:
            proposed_update = self.narrative_revision.update_recent_layer(
                experiences, ReflectionLevel.MICRO
            )
        except NarrativePersistenceConflictError:
            event = ReflectionEvent(
                reflection_level=ReflectionLevel.MICRO,
                experiences_analyzed=[exp.id for exp in experiences],
                narrative_changes_proposed="",
                key_insight=(
                    "Micro reflection did not apply: narrative was modified "
                    "concurrently since this snapshot was read."
                ),
                notes="outcome=micro_failed reason=narrative_conflict",
                timestamp=self._clock.now(),
            )
            self.event_store.save(event)
            return event

        event = ReflectionEvent(
            reflection_level=ReflectionLevel.MICRO,
            experiences_analyzed=[exp.id for exp in experiences],
            narrative_changes_proposed=proposed_update,
            key_insight="Micro reflection completed - recent layer updated",
            timestamp=self._clock.now(),
        )

        try:
            self.event_store.save(event)
        except Exception as exc:
            self._reflection_event_observer.record_reflection_event_save_failed_after_narrative_commit(
                reflection_level=ReflectionLevel.MICRO,
                error_message=f"{type(exc).__name__}: {exc}",
            )
            raise

        # Skill-loop hook: process invocations, update stats, auto-pin/downgrade.
        # Runs after narrative update; errors are logged but never surface to caller.
        if self._skill_manager is not None and agent_id is not None:
            import logging as _logging

            try:
                self._skill_manager.process_session_skills(agent_id, session_id)
            except Exception as _exc:
                _logging.getLogger(__name__).warning(
                    "Skill-loop processing failed for session %s: %s", session_id, _exc
                )

        return event

    def _create_skipped_micro_event(
        self,
        *,
        reason: Literal["no_experiences", "no_narrative"],
        experience_ids: list[UUID],
    ) -> ReflectionEvent:
        """Persist a skipped micro-reflection (distinct from successful completion)."""
        if reason == "no_experiences":
            key_insight = "No experiences to reflect on for this session."
            notes = "outcome=micro_skipped reason=no_experiences"
        else:
            key_insight = (
                "Cannot update narrative: no current narrative document is loaded "
                f"({len(experience_ids)} experience(s) were available)."
            )
            notes = "outcome=micro_skipped reason=no_narrative"

        event = ReflectionEvent(
            reflection_level=ReflectionLevel.MICRO,
            experiences_analyzed=list(experience_ids),
            key_insight=key_insight,
            notes=notes,
            timestamp=self._clock.now(),
        )
        self.event_store.save(event)
        return event


class DailyReflectionService:
    """
    Daily-level reflection: pattern detection across sessions.

    This runs at the end of each day and:
    - Analyzes all experiences from the day
    - Detects recurring patterns
    - May add reframing notes to experiences
    - May update open questions

    Does NOT modify core identity unless patterns are very strong.

    Runs are idempotent per calendar day and identity via ``reflection_run_key``.
    """

    def __init__(
        self,
        session_repo: SessionRepository,
        identity_repo: IdentityRepository,
        pattern_store: PatternStore,
        reflection_model: ReflectionModel,
        event_store: ReflectionEventStore,
        *,
        clock: ClockPort | None = None,
        reflection_event_observer: ReflectionEventPersistenceObserver | None = None,
        structured_markers_aggregator: StructuredMarkersAggregator | None = None,
        reflection_request_queue: ReflectionRequestQueue | None = None,
    ):
        """Initialize daily reflection service."""
        self.session_repo = session_repo
        self.identity_repo = identity_repo
        self.pattern_store = pattern_store
        self.reflection_model = reflection_model
        self.event_store = event_store
        self._clock = clock or SystemClock()
        self._reflection_event_observer = (
            reflection_event_observer or NoOpReflectionEventPersistenceObserver()
        )
        self._structured_markers_aggregator = (
            structured_markers_aggregator or StructuredMarkersAggregator(pattern_store)
        )
        self._reflection_request_queue = reflection_request_queue

    def reflect(self, date: datetime) -> ReflectionEvent:
        """
        Perform daily reflection for a specific date.

        Args:
            date: Anchor instant for the **UTC calendar day** to analyze. Naive
                datetimes are treated as UTC wall time (see :func:`~atman.core.clock_impl.ensure_utc`).

        Returns:
            ReflectionEvent recording what was done
        """
        calendar_anchor = ensure_utc(date)
        start, end = _utc_calendar_day_bounds(calendar_anchor)

        sessions = self.session_repo.get_sessions_in_range(start, end)
        experiences: list[SessionExperience] = []
        all_moments: list = []
        for s in sessions:
            moments = self.session_repo.get_key_moments_for_session(s.id)
            if not moments:
                continue
            all_moments.extend(moments)
            experiences.append(build_session_experience(s, moments))

        # Drain agent-driven reflection requests at the daily level. Even with
        # no experiences for the day we still want to acknowledge pending
        # requests so they don't pile up forever — they get consumed on the
        # empty event.
        pending_requests = _take_pending_requests(
            self._reflection_request_queue, ReflectionRequestLevel.DAILY
        )

        if not experiences:
            event = self._create_empty_event(calendar_anchor)
            _mark_requests_consumed(
                self._reflection_request_queue,
                pending_requests,
                event,
                self._clock.now(),
            )
            return event

        identity = self.identity_repo.get_current()
        if not identity:
            event = self._create_skipped_daily_no_identity(
                calendar_anchor, [exp.id for exp in experiences]
            )
            _mark_requests_consumed(
                self._reflection_request_queue,
                pending_requests,
                event,
                self._clock.now(),
            )
            return event

        run_key = daily_reflection_run_key_for_identity(calendar_anchor, identity.id)
        existing = self.event_store.get_by_reflection_run_key(run_key)
        if existing is not None and _daily_run_terminal_success(existing.notes or ""):
            # Replay path: don't drain again — leave them for the next live run.
            return existing

        anchor_snapshot_id = _reflection_identity_anchor_snapshot_id(
            self.identity_repo, identity, run_key
        )

        agent_reasons = [r.reason for r in pending_requests]
        patterns_detected = self._detect_patterns(
            experiences, identity, run_key, agent_reasons=agent_reasons
        )
        reframing_count, reframing_nf, reframing_sr, reframing_dup = self._add_reframing_notes(
            experiences, patterns_detected, run_key
        )
        # Marker-aggregation runs after reframing so the LLM-driven reframing
        # prompt isn't polluted with deterministic marker descriptions.
        marker_patterns = self._structured_markers_aggregator.analyze(all_moments, run_key=run_key)
        patterns_detected.extend(marker_patterns)

        notes = "outcome=daily_ok"
        if reframing_nf or reframing_sr:
            notes += (
                f" signal=reframing_append_degraded not_found={reframing_nf} "
                f"storage_rejected={reframing_sr}"
            )
        if reframing_dup:
            notes += f" reframing_duplicate_triggered_by={reframing_dup}"
        if pending_requests:
            notes += f" agent_driven_requests={len(pending_requests)}"

        key_insight = f"Daily reflection: {len(patterns_detected)} patterns detected"
        if agent_reasons:
            joined = "; ".join(agent_reasons[:3])
            key_insight = f"{key_insight}. Agent asked to look at: {joined}"

        event = ReflectionEvent(
            reflection_level=ReflectionLevel.DAILY,
            experiences_analyzed=[exp.id for exp in experiences],
            patterns_detected=[p.id for p in patterns_detected],
            reframing_notes_added=reframing_count,
            reframing_experience_not_found_count=reframing_nf,
            reframing_append_storage_rejected_count=reframing_sr,
            reframing_duplicate_triggered_by_count=reframing_dup,
            key_insight=key_insight,
            notes=notes,
            reflection_run_key=run_key,
            identity_snapshot_id=anchor_snapshot_id,
            timestamp=self._clock.now(),
        )

        try:
            self.event_store.save(event)
        except Exception as exc:
            self._reflection_event_observer.record_reflection_job_event_save_failed_after_side_effects(
                reflection_level=ReflectionLevel.DAILY,
                reflection_run_key=run_key,
                error_message=f"{type(exc).__name__}: {exc}",
            )
            raise
        got = self.event_store.get_by_reflection_run_key(run_key)
        persisted = got if got is not None else event
        _mark_requests_consumed(
            self._reflection_request_queue,
            pending_requests,
            persisted,
            self._clock.now(),
        )
        return persisted

    def _detect_patterns(
        self,
        experiences: list[SessionExperience],
        identity: Identity,
        run_key: str,
        *,
        agent_reasons: list[str] | None = None,
    ) -> list[PatternCandidate]:
        """Detect patterns across experiences."""
        if len(experiences) < 2:
            return []

        context = {
            "identity_values": ", ".join(v.name for v in identity.core_values),
            "known_habits": ", ".join(h.statement for h in identity.habits),
        }
        if agent_reasons:
            # Pre-pend agent-driven reasons so the LLM sees them as priority
            # framing for this run.
            context["agent_requested_focus"] = " | ".join(agent_reasons)

        detection = self.reflection_model.detect_pattern(experiences=experiences, context=context)
        pattern_description = detection.description.strip()

        if not pattern_description or len(pattern_description) < 10:
            return []

        conf = detection.confidence if detection.confidence is not None else 0.6
        detection_key = daily_pattern_detection_key(run_key, PatternType.BEHAVIOR.value)
        pattern = PatternCandidate(
            pattern_type=PatternType.BEHAVIOR,
            description=pattern_description,
            examples=[exp.id for exp in experiences[:3]],
            detected_by=ReflectionLevel.DAILY,
            confidence=conf,
            potential_habit=detection.potential_habit,
            potential_principle=detection.potential_principle,
        )

        stored = self.pattern_store.save_with_detection_key(detection_key, pattern)
        return [stored]

    def _add_reframing_notes(
        self,
        experiences: list[SessionExperience],
        patterns: list[PatternCandidate],
        run_key: str,
    ) -> tuple[int, int, int, int]:
        """Add reframing notes; return (stored, not_found, storage_rejected, duplicate_triggered_by)."""
        if not patterns:
            return (0, 0, 0, 0)

        count = 0
        not_found = 0
        storage_rejected = 0
        duplicate = 0
        for exp in experiences[:2]:
            context = {"patterns": ", ".join(p.description for p in patterns)}

            reframing_out = self.reflection_model.generate_reframing_note(
                experience=exp, context=context
            )
            reframing_text = reframing_out.reflection.strip()

            if reframing_text and len(reframing_text) > 10:
                note = ReframingNote(
                    reflection=reframing_text,
                    reflection_type=reframing_out.reflection_type,
                    triggered_by=reframing_trigger_key(run_key, exp.id),
                )
                outcome = self.session_repo.add_reframing_note(exp.id, note)
                if outcome == ReframingNoteAppendResult.STORED:
                    count += 1
                elif outcome == ReframingNoteAppendResult.EXPERIENCE_NOT_FOUND:
                    not_found += 1
                elif outcome == ReframingNoteAppendResult.STORAGE_REJECTED:
                    storage_rejected += 1
                elif outcome == ReframingNoteAppendResult.DUPLICATE_TRIGGERED_BY:
                    duplicate += 1

        return (count, not_found, storage_rejected, duplicate)

    def _create_empty_event(self, date: datetime) -> ReflectionEvent:
        """Create an event for when there's nothing to reflect on."""
        run_key = daily_reflection_run_key_empty_day(date)
        existing = self.event_store.get_by_reflection_run_key(run_key)
        if existing is not None and "outcome=daily_empty" in (existing.notes or ""):
            return existing

        day_iso = ensure_utc(date).date().isoformat()
        event = ReflectionEvent(
            reflection_level=ReflectionLevel.DAILY,
            experiences_analyzed=[],
            key_insight=f"No experiences on {day_iso}",
            notes="outcome=daily_empty reason=no_experiences",
            reflection_run_key=run_key,
            timestamp=self._clock.now(),
        )

        self.event_store.save(event)
        got = self.event_store.get_by_reflection_run_key(run_key)
        return got if got is not None else event

    def _create_skipped_daily_no_identity(
        self, date: datetime, experience_ids: list[UUID]
    ) -> ReflectionEvent:
        """Experiences exist but identity is missing — distinct from an empty day."""
        run_key = daily_reflection_run_key_no_identity(date, experience_ids)
        existing = self.event_store.get_by_reflection_run_key(run_key)
        if existing is not None and "outcome=daily_skipped" in (existing.notes or ""):
            return existing

        n = len(experience_ids)
        day_iso = ensure_utc(date).date().isoformat()
        event = ReflectionEvent(
            reflection_level=ReflectionLevel.DAILY,
            experiences_analyzed=list(experience_ids),
            key_insight=(
                f"Daily reflection skipped: no current identity loaded "
                f"({n} experience(s) on {day_iso})."
            ),
            notes="outcome=daily_skipped reason=no_identity",
            reflection_run_key=run_key,
            timestamp=self._clock.now(),
        )
        self.event_store.save(event)
        got = self.event_store.get_by_reflection_run_key(run_key)
        return got if got is not None else event


class DeepReflectionService:
    """
    Deep-level reflection: identity revision and health assessment.

    This runs on schedule (weekly/monthly) and:
    - Analyzes experiences across extended period
    - Performs health assessment on 6 Jahoda criteria
    - Proposes changes to identity (values, principles, habits) as text on the
      :class:`~atman.core.models.reflection.ReflectionEvent` (not persisted to
      ``Identity`` here)
    - Proposes narrative text on the same event (core layer is **not** written
      by this service; use :class:`~atman.core.services.narrative_revision.NarrativeRevisionService` under governance)
    - Adds strategic reframing notes

    This is the most comprehensive reflection level.
    """

    def __init__(
        self,
        session_repo: SessionRepository,
        identity_repo: IdentityRepository,
        narrative_repo: NarrativeRepository,
        pattern_store: PatternStore,
        health_store: HealthAssessmentStore,
        reflection_model: ReflectionModel,
        event_store: ReflectionEventStore,
        *,
        clock: ClockPort | None = None,
        reflection_event_observer: ReflectionEventPersistenceObserver | None = None,
        reflection_request_queue: ReflectionRequestQueue | None = None,
        entity_relations_formulator: EntityRelationsFormulator | None = None,
        agent_id: UUID | None = None,
    ):
        """Initialize deep reflection service."""
        self.session_repo = session_repo
        self.identity_repo = identity_repo
        self.narrative_repo = narrative_repo
        self.pattern_store = pattern_store
        self.health_store = health_store
        self.reflection_model = reflection_model
        self.event_store = event_store
        self._clock = clock or SystemClock()
        self._reflection_event_observer = (
            reflection_event_observer or NoOpReflectionEventPersistenceObserver()
        )
        self._reflection_request_queue = reflection_request_queue
        self._entity_relations_formulator = entity_relations_formulator
        self._agent_id = agent_id

    def reflect(self, since: datetime, until: datetime) -> ReflectionEvent:
        """
        Perform deep reflection over a period.

        Args:
            since: Start of reflection period (inclusive). Naive values are UTC wall time.
            until: End of reflection period (inclusive). Naive values are UTC wall time.

        Returns:
            ReflectionEvent recording what was done
        """
        since_utc = ensure_utc(since)
        until_utc = ensure_utc(until)
        sessions = self.session_repo.get_sessions_in_range(since_utc, until_utc)
        experiences: list[SessionExperience] = []
        for s in sessions:
            moments = self.session_repo.get_key_moments_for_session(s.id)
            if not moments:
                continue
            experiences.append(build_session_experience(s, moments))

        pending_requests = _take_pending_requests(
            self._reflection_request_queue, ReflectionRequestLevel.DEEP
        )

        if not experiences:
            event = self._create_empty_event(since_utc, until_utc)
            _mark_requests_consumed(
                self._reflection_request_queue,
                pending_requests,
                event,
                self._clock.now(),
            )
            return event

        identity = self.identity_repo.get_current()
        if not identity:
            event = self._create_skipped_deep_no_identity(
                since_utc, until_utc, [exp.id for exp in experiences]
            )
            _mark_requests_consumed(
                self._reflection_request_queue,
                pending_requests,
                event,
                self._clock.now(),
            )
            return event

        run_key = deep_reflection_run_key_for_identity(since_utc, until_utc, identity.id)
        existing = self.event_store.get_by_reflection_run_key(run_key)
        if existing is not None and _deep_run_terminal_success(existing.notes or ""):
            # Replay path — don't drain the queue again.
            return existing

        anchor_snapshot_id = _reflection_identity_anchor_snapshot_id(
            self.identity_repo, identity, run_key
        )

        health_assessment = self._perform_health_assessment(identity, experiences, run_key)

        agent_reasons = [r.reason for r in pending_requests]
        patterns_detected = self._detect_deep_patterns(
            experiences, identity, run_key, agent_reasons=agent_reasons
        )
        reframing_count, reframing_nf, reframing_sr, reframing_dup = self._add_strategic_reframing(
            experiences, patterns_detected, run_key
        )

        narrative_changes = self._propose_narrative_revision(
            experiences, identity, patterns_detected
        )

        identity_changes = self._propose_identity_revision(
            identity, patterns_detected, health_assessment
        )

        # R9 Deep — formulate typed relations between co-occurring entities.
        relation_outcome = None
        if self._entity_relations_formulator is not None and self._agent_id is not None:
            try:
                relation_outcome = self._entity_relations_formulator.run(self._agent_id)
            except Exception:  # pragma: no cover - defensive
                relation_outcome = None

        notes = "outcome=deep_ok"
        if reframing_nf or reframing_sr:
            notes += (
                f" signal=reframing_append_degraded not_found={reframing_nf} "
                f"storage_rejected={reframing_sr}"
            )
        if reframing_dup:
            notes += f" reframing_duplicate_triggered_by={reframing_dup}"
        if pending_requests:
            notes += f" agent_driven_requests={len(pending_requests)}"
        if relation_outcome is not None and (
            relation_outcome.formulated or relation_outcome.pairs_considered
        ):
            notes += (
                f" entity_relations_formulated={relation_outcome.formulated}"
                f" entity_relations_pairs={relation_outcome.pairs_considered}"
            )

        key_insight = (
            f"Deep reflection: {len(patterns_detected)} patterns, "
            f"health score {health_assessment.overall_score:.2f}"
        )
        if agent_reasons:
            joined = "; ".join(agent_reasons[:3])
            key_insight = f"{key_insight}. Agent asked to look at: {joined}"

        event = ReflectionEvent(
            reflection_level=ReflectionLevel.DEEP,
            experiences_analyzed=[exp.id for exp in experiences],
            patterns_detected=[p.id for p in patterns_detected],
            reframing_notes_added=reframing_count,
            reframing_experience_not_found_count=reframing_nf,
            reframing_append_storage_rejected_count=reframing_sr,
            reframing_duplicate_triggered_by_count=reframing_dup,
            narrative_changes_proposed=narrative_changes,
            identity_changes_proposed=identity_changes,
            health_assessment_id=health_assessment.id,
            key_insight=key_insight,
            notes=notes,
            reflection_run_key=run_key,
            identity_snapshot_id=anchor_snapshot_id,
            timestamp=self._clock.now(),
        )

        health_persisted = False
        try:
            self.health_store.save(health_assessment)
            health_persisted = True
            self.event_store.save(event)
        except Exception as exc:
            self._reflection_event_observer.record_reflection_job_event_save_failed_after_side_effects(
                reflection_level=ReflectionLevel.DEEP,
                reflection_run_key=run_key,
                error_message=f"{type(exc).__name__}: {exc}",
            )
            failed = ReflectionEvent(
                reflection_level=ReflectionLevel.DEEP,
                experiences_analyzed=[exp.id for exp in experiences],
                patterns_detected=[p.id for p in patterns_detected],
                reframing_notes_added=reframing_count,
                reframing_experience_not_found_count=reframing_nf,
                reframing_append_storage_rejected_count=reframing_sr,
                reframing_duplicate_triggered_by_count=reframing_dup,
                narrative_changes_proposed=narrative_changes,
                identity_changes_proposed=identity_changes,
                health_assessment_id=health_assessment.id if health_persisted else None,
                key_insight=(
                    "Deep reflection did not complete a durable success record "
                    f"({type(exc).__name__})."
                ),
                notes=f"outcome=deep_failed reason=persist err={type(exc).__name__}",
                reflection_run_key=run_key,
                identity_snapshot_id=anchor_snapshot_id,
                timestamp=self._clock.now(),
            )
            with contextlib.suppress(Exception):
                self.event_store.save(failed)
            raise
        got = self.event_store.get_by_reflection_run_key(run_key)
        persisted = got if got is not None else event
        _mark_requests_consumed(
            self._reflection_request_queue,
            pending_requests,
            persisted,
            self._clock.now(),
        )
        return persisted

    def _perform_health_assessment(
        self, identity: Identity, experiences: list[SessionExperience], run_key: str
    ) -> HealthAssessment:
        """Perform health assessment on 6 Jahoda criteria."""
        criteria: dict[JahodaCriterion, CriterionAssessment] = {}

        for criterion in JahodaCriterion:
            hc = self.reflection_model.assess_health_criterion(
                identity=identity, experiences=experiences, criterion=criterion
            )

            criteria[criterion] = CriterionAssessment(
                criterion=criterion,
                score=hc.score,
                evidence=hc.evidence,
                concerns=hc.concerns,
            )

        overall_score = sum(c.score for c in criteria.values()) / len(criteria)

        return HealthAssessment(
            id=health_assessment_id_for_run_key(run_key),
            criteria=criteria,
            overall_score=overall_score,
            summary=f"Health assessment: {overall_score:.2f}/1.0",
            recommendations=["Continue honest reflection", "Seek diverse experiences"],
            timestamp=self._clock.now(),
        )

    def _detect_deep_patterns(
        self,
        experiences: list[SessionExperience],
        identity: Identity,
        run_key: str,
        *,
        agent_reasons: list[str] | None = None,
    ) -> list[PatternCandidate]:
        """Detect patterns across extended period."""
        if len(experiences) < 3:
            return []

        patterns: list[PatternCandidate] = []

        for pattern_type in [PatternType.BEHAVIOR, PatternType.EMOTIONAL]:
            context = {
                "identity_values": ", ".join(v.name for v in identity.core_values),
                "pattern_type": pattern_type.value,
            }
            if agent_reasons:
                context["agent_requested_focus"] = " | ".join(agent_reasons)

            detection = self.reflection_model.detect_pattern(
                experiences=experiences, context=context
            )
            pattern_description = detection.description.strip()

            if pattern_description and len(pattern_description) > 10:
                conf = detection.confidence if detection.confidence is not None else 0.7
                detection_key = deep_pattern_detection_key(run_key, pattern_type.value)
                pattern = PatternCandidate(
                    pattern_type=pattern_type,
                    description=pattern_description,
                    examples=[exp.id for exp in experiences[:5]],
                    detected_by=ReflectionLevel.DEEP,
                    confidence=conf,
                    potential_habit=detection.potential_habit,
                    potential_principle=detection.potential_principle,
                )
                stored = self.pattern_store.save_with_detection_key(detection_key, pattern)
                patterns.append(stored)

        return patterns

    def _add_strategic_reframing(
        self,
        experiences: list[SessionExperience],
        patterns: list[PatternCandidate],
        run_key: str,
    ) -> tuple[int, int, int, int]:
        """Add strategic reframing; return (stored, not_found, storage_rejected, duplicate_triggered_by)."""
        if not patterns:
            return (0, 0, 0, 0)

        count = 0
        not_found = 0
        storage_rejected = 0
        duplicate = 0
        for exp in experiences[:3]:
            context = {"patterns": ", ".join(p.description for p in patterns)}

            reframing_out = self.reflection_model.generate_reframing_note(
                experience=exp, context=context
            )
            reframing_text = reframing_out.reflection.strip()

            if reframing_text and len(reframing_text) > 10:
                note = ReframingNote(
                    reflection=reframing_text,
                    reflection_type=reframing_out.reflection_type,
                    triggered_by=reframing_trigger_key(run_key, exp.id),
                )
                outcome = self.session_repo.add_reframing_note(exp.id, note)
                if outcome == ReframingNoteAppendResult.STORED:
                    count += 1
                elif outcome == ReframingNoteAppendResult.EXPERIENCE_NOT_FOUND:
                    not_found += 1
                elif outcome == ReframingNoteAppendResult.STORAGE_REJECTED:
                    storage_rejected += 1
                elif outcome == ReframingNoteAppendResult.DUPLICATE_TRIGGERED_BY:
                    duplicate += 1

        return (count, not_found, storage_rejected, duplicate)

    def _propose_narrative_revision(
        self,
        experiences: list[SessionExperience],
        identity: Identity,
        patterns: list[PatternCandidate],
    ) -> str:
        """Propose revisions to narrative based on patterns."""
        narrative = self.narrative_repo.get_current()
        if not narrative:
            return "No narrative to revise"

        proposed = self.reflection_model.propose_narrative_update(
            current_narrative=narrative,
            recent_experiences=experiences,
            reflection_level=ReflectionLevel.DEEP,
        )

        return proposed.body

    def _propose_identity_revision(
        self,
        identity: Identity,
        patterns: list[PatternCandidate],
        health: HealthAssessment,
    ) -> str:
        """Propose revisions to identity based on patterns and health."""
        proposals = []

        for pattern in patterns:
            if pattern.potential_habit:
                proposals.append(f"New habit: {pattern.potential_habit}")
            if pattern.potential_principle:
                proposals.append(f"New principle: {pattern.potential_principle}")

        if health.overall_score < 0.5:
            proposals.append("Consider reviewing principles in light of low health score")

        return "; ".join(proposals) if proposals else "No identity changes proposed"

    def _create_empty_event(self, since: datetime, until: datetime) -> ReflectionEvent:
        """Create an event for when there's nothing to reflect on."""
        run_key = deep_reflection_run_key_empty(since, until)
        existing = self.event_store.get_by_reflection_run_key(run_key)
        if existing is not None and "outcome=deep_empty" in (existing.notes or ""):
            return existing

        since_d = ensure_utc(since).date().isoformat()
        until_d = ensure_utc(until).date().isoformat()
        event = ReflectionEvent(
            reflection_level=ReflectionLevel.DEEP,
            experiences_analyzed=[],
            key_insight=(f"No experiences from {since_d} to {until_d}"),
            notes="outcome=deep_empty reason=no_experiences",
            reflection_run_key=run_key,
            timestamp=self._clock.now(),
        )
        self.event_store.save(event)
        got = self.event_store.get_by_reflection_run_key(run_key)
        return got if got is not None else event

    def _create_skipped_deep_no_identity(
        self, since: datetime, until: datetime, experience_ids: list[UUID]
    ) -> ReflectionEvent:
        """Experiences in range but identity missing — distinct from an empty period."""
        run_key = deep_reflection_run_key_no_identity(since, until, experience_ids)
        existing = self.event_store.get_by_reflection_run_key(run_key)
        if existing is not None and "outcome=deep_skipped" in (existing.notes or ""):
            return existing

        n = len(experience_ids)
        since_d = ensure_utc(since).date().isoformat()
        until_d = ensure_utc(until).date().isoformat()
        event = ReflectionEvent(
            reflection_level=ReflectionLevel.DEEP,
            experiences_analyzed=list(experience_ids),
            key_insight=(
                "Deep reflection skipped: no current identity loaded "
                f"({n} experience(s) from {since_d} to {until_d})."
            ),
            notes="outcome=deep_skipped reason=no_identity",
            reflection_run_key=run_key,
            timestamp=self._clock.now(),
        )
        self.event_store.save(event)
        got = self.event_store.get_by_reflection_run_key(run_key)
        return got if got is not None else event
