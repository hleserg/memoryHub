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
from atman.core.models.experience import (
    KeyMoment,
    ReframingNote,
    ReframingNoteAppendResult,
    SessionExperience,
)
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
from atman.core.services.divergence_aggregator import DivergenceAggregator
from atman.core.services.entity_relations_formulator import EntityRelationsFormulator
from atman.core.services.entity_stance_formulator import EntityStanceFormulator
from atman.core.services.findings_triage import FindingsTriage, TriageOutcome
from atman.core.services.merge_candidates_handler import MergeCandidatesHandler
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
def _run_terminal_success(notes: str, prefix: str) -> bool:
    """Return True when ``notes`` carries a terminal-success outcome for ``prefix``.

    ``prefix`` is the reflection level tag used in the run-key contract
    (``"daily"`` or ``"deep"``). Terminal outcomes are ``{prefix}_ok``,
    ``{prefix}_empty`` and ``{prefix}_skipped`` — anything else is treated
    as "did not finish" and the run will be retried.
    """
    return any(f"outcome={prefix}_{suffix}" in notes for suffix in ("ok", "empty", "skipped"))


def _apply_reframing_notes(
    *,
    reflection_model: ReflectionModel,
    session_repo: SessionRepository,
    experiences: list[SessionExperience],
    patterns: list[PatternCandidate],
    run_key: str,
    max_experiences: int,
    key_moments_by_session: dict[UUID, list[KeyMoment]] | None = None,
) -> tuple[int, int, int, int]:
    """Generate and persist reframing notes for the first ``max_experiences`` experiences.

    Returns ``(stored, not_found, storage_rejected, duplicate_triggered_by)``.
    Shared by daily (``max_experiences=2``) and deep (``max_experiences=3``)
    reflection paths so the reframing contract stays single-sourced.
    """
    if not patterns:
        return (0, 0, 0, 0)

    stored = not_found = storage_rejected = duplicate = 0
    for exp in experiences[:max_experiences]:
        context = {"patterns": ", ".join(p.description for p in patterns)}
        reframing_out = reflection_model.generate_reframing_note(
            experience=exp,
            context=context,
            key_moments_by_session=key_moments_by_session,
        )
        reframing_text = reframing_out.reflection.strip()
        if not (reframing_text and len(reframing_text) > 10):
            continue

        note = ReframingNote(
            reflection=reframing_text,
            reflection_type=reframing_out.reflection_type,
            triggered_by=reframing_trigger_key(run_key, exp.id),
        )
        outcome = session_repo.add_reframing_note(exp.id, note)
        if outcome == ReframingNoteAppendResult.STORED:
            stored += 1
        elif outcome == ReframingNoteAppendResult.EXPERIENCE_NOT_FOUND:
            not_found += 1
        elif outcome == ReframingNoteAppendResult.STORAGE_REJECTED:
            storage_rejected += 1
        elif outcome == ReframingNoteAppendResult.DUPLICATE_TRIGGERED_BY:
            duplicate += 1

    return (stored, not_found, storage_rejected, duplicate)


def _read_persisted_event(
    event_store: ReflectionEventStore, event: ReflectionEvent
) -> ReflectionEvent:
    """Re-read ``event`` by its run-key; fall back to the in-memory copy.

    Used after a successful save to give callers the canonical persisted row
    (implementations may upsert by run-key) without coupling them to the
    store's read API.
    """
    if event.reflection_run_key:
        stored = event_store.get_by_reflection_run_key(event.reflection_run_key)
        if stored is not None:
            return stored
    return event


def _save_and_get_event(
    event_store: ReflectionEventStore, event: ReflectionEvent
) -> ReflectionEvent:
    """Save ``event`` and return the canonical persisted instance."""
    event_store.save(event)
    return _read_persisted_event(event_store, event)


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


# HLE-46: cap how many moments per session we ship to the LLM prompt. The
# prompt-builder already truncates each session block to its top-3 by
# salience, but we cap at the service layer too so we never hold more than
# necessary in memory while building the per-session map.
_MAX_MOMENTS_PER_SESSION_FOR_PROMPT = 5


def _top_moments_by_session(
    moments_by_session: dict[UUID, list[KeyMoment]],
    *,
    per_session_cap: int = _MAX_MOMENTS_PER_SESSION_FOR_PROMPT,
) -> dict[UUID, list[KeyMoment]]:
    """Return a copy with each session's moments sorted by salience desc and capped."""
    out: dict[UUID, list[KeyMoment]] = {}
    for sid, ms in moments_by_session.items():
        if not ms:
            continue
        ranked = sorted(ms, key=lambda m: m.salience, reverse=True)
        out[sid] = ranked[:per_session_cap]
    return out


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

        # HLE-46: forward the session's KeyMoments to the prompt builder via
        # NarrativeRevisionService so the LLM sees actual moment content.
        key_moments_by_session = _top_moments_by_session({session_id: moments})
        try:
            proposed_update = self.narrative_revision.update_recent_layer(
                experiences,
                ReflectionLevel.MICRO,
                key_moments_by_session=key_moments_by_session,
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
        entity_stance_formulator: EntityStanceFormulator | None = None,
        reflection_request_queue: ReflectionRequestQueue | None = None,
        divergence_aggregator: DivergenceAggregator | None = None,
        findings_triage: FindingsTriage | None = None,
        agent_id: UUID | None = None,
    ):
        """Initialize daily reflection service.

        Optional R6/R8 hooks: ``divergence_aggregator`` summarises
        ``divergence_events`` (recurring types → behaviour patterns;
        ``rupture`` severity → key_insight observations); ``findings_triage``
        resolves level-B ``validation_findings`` by policy. Both require
        ``agent_id`` to scope the query.
        """
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
        self._entity_stance_formulator = entity_stance_formulator
        self._reflection_request_queue = reflection_request_queue
        self._divergence_aggregator = divergence_aggregator
        self._findings_triage = findings_triage
        self._agent_id = agent_id

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
        # HLE-46: keep per-session moments so the reflection prompts can render
        # the actual content of each KeyMoment, not just aggregate counters.
        moments_by_session: dict[UUID, list[KeyMoment]] = {}
        for s in sessions:
            moments = self.session_repo.get_key_moments_for_session(s.id)
            if not moments:
                continue
            all_moments.extend(moments)
            moments_by_session[s.id] = moments
            experiences.append(build_session_experience(s, moments))
        key_moments_by_session = _top_moments_by_session(moments_by_session)

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
        if existing is not None and _run_terminal_success(existing.notes or "", "daily"):
            # Replay path: don't drain again — leave them for the next live run.
            return existing

        anchor_snapshot_id = _reflection_identity_anchor_snapshot_id(
            self.identity_repo, identity, run_key
        )

        agent_reasons = [r.reason for r in pending_requests]
        patterns_detected = self._detect_patterns(
            experiences,
            identity,
            run_key,
            agent_reasons=agent_reasons,
            key_moments_by_session=key_moments_by_session,
        )
        reframing_count, reframing_nf, reframing_sr, reframing_dup = self._add_reframing_notes(
            experiences,
            patterns_detected,
            run_key,
            key_moments_by_session=key_moments_by_session,
        )
        # Marker-aggregation runs after reframing so the LLM-driven reframing
        # prompt isn't polluted with deterministic marker descriptions.
        marker_patterns = self._structured_markers_aggregator.analyze(all_moments, run_key=run_key)
        patterns_detected.extend(marker_patterns)

        # R7: formulate per-entity stances. Runs only when both the
        # formulator and an agent_id are configured — the formulator needs
        # an agent scope to query EntityRegistry.
        stance_outcome = None
        if self._entity_stance_formulator is not None and self._agent_id is not None:
            try:
                stance_outcome = self._entity_stance_formulator.formulate_for_new_entities(
                    self._agent_id
                )
            except Exception:  # pragma: no cover - defensive
                stance_outcome = None

        # R6: aggregate divergence_events for the day (optional hook).
        divergence_patterns, rupture_observations = self._aggregate_divergences(start, end, run_key)
        patterns_detected.extend(divergence_patterns)

        # R8: triage level-B validation_findings (optional hook).
        triage_outcome = self._triage_findings()

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
        if divergence_patterns:
            notes += f" divergence_patterns={len(divergence_patterns)}"
        if rupture_observations:
            notes += f" divergence_ruptures={len(rupture_observations)}"
        if triage_outcome is not None:
            notes += (
                f" findings_triage_resolved={triage_outcome.resolved_count}"
                f" findings_triage_attention={triage_outcome.requires_attention_count}"
            )
        if stance_outcome is not None and (stance_outcome.formulated or stance_outcome.skipped):
            notes += f" entity_stances_formulated={stance_outcome.formulated}"

        key_insight_parts = [f"Daily reflection: {len(patterns_detected)} patterns detected"]
        if agent_reasons:
            joined = "; ".join(agent_reasons[:3])
            key_insight_parts.append(f"Agent asked to look at: {joined}")
        if rupture_observations:
            joined = "; ".join(rupture_observations[:3])
            key_insight_parts.append(f"Ruptures observed: {joined}")
        key_insight = ". ".join(key_insight_parts)

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
        persisted = _read_persisted_event(self.event_store, event)
        _mark_requests_consumed(
            self._reflection_request_queue,
            pending_requests,
            persisted,
            self._clock.now(),
        )
        return persisted

    def _aggregate_divergences(
        self, start: datetime, end: datetime, run_key: str
    ) -> tuple[list[PatternCandidate], list[str]]:
        """R6 hook. Returns (patterns, rupture_observations); silent if not configured."""
        if self._divergence_aggregator is None or self._agent_id is None:
            return ([], [])
        return self._divergence_aggregator.analyze(
            agent_id=self._agent_id, start=start, end=end, run_key=run_key
        )

    def _triage_findings(self) -> TriageOutcome | None:
        """R8 hook. Returns TriageOutcome or None when no triage is wired."""
        if self._findings_triage is None or self._agent_id is None:
            return None
        return self._findings_triage.run(self._agent_id)

    def _detect_patterns(
        self,
        experiences: list[SessionExperience],
        identity: Identity,
        run_key: str,
        *,
        agent_reasons: list[str] | None = None,
        key_moments_by_session: dict[UUID, list[KeyMoment]] | None = None,
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

        detection = self.reflection_model.detect_pattern(
            experiences=experiences,
            context=context,
            key_moments_by_session=key_moments_by_session,
        )
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
        *,
        key_moments_by_session: dict[UUID, list[KeyMoment]] | None = None,
    ) -> tuple[int, int, int, int]:
        """Add reframing notes; return (stored, not_found, storage_rejected, duplicate_triggered_by)."""
        return _apply_reframing_notes(
            reflection_model=self.reflection_model,
            session_repo=self.session_repo,
            experiences=experiences,
            patterns=patterns,
            run_key=run_key,
            max_experiences=2,
            key_moments_by_session=key_moments_by_session,
        )

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

        return _save_and_get_event(self.event_store, event)

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
        return _save_and_get_event(self.event_store, event)


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
        entity_stance_formulator: EntityStanceFormulator | None = None,
        reflection_request_queue: ReflectionRequestQueue | None = None,
        entity_relations_formulator: EntityRelationsFormulator | None = None,
        merge_candidates_handler: MergeCandidatesHandler | None = None,
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
        self._entity_stance_formulator = entity_stance_formulator
        self._reflection_request_queue = reflection_request_queue
        self._entity_relations_formulator = entity_relations_formulator
        self._merge_candidates_handler = merge_candidates_handler
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
        # HLE-46: per-session moments fed to the LLM prompt builders.
        moments_by_session: dict[UUID, list[KeyMoment]] = {}
        for s in sessions:
            moments = self.session_repo.get_key_moments_for_session(s.id)
            if not moments:
                continue
            moments_by_session[s.id] = moments
            experiences.append(build_session_experience(s, moments))
        key_moments_by_session = _top_moments_by_session(moments_by_session)

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
        if existing is not None and _run_terminal_success(existing.notes or "", "deep"):
            # Replay path — don't drain the queue again.
            return existing

        anchor_snapshot_id = _reflection_identity_anchor_snapshot_id(
            self.identity_repo, identity, run_key
        )

        health_assessment = self._perform_health_assessment(
            identity, experiences, run_key, key_moments_by_session=key_moments_by_session
        )

        agent_reasons = [r.reason for r in pending_requests]
        patterns_detected = self._detect_deep_patterns(
            experiences,
            identity,
            run_key,
            agent_reasons=agent_reasons,
            key_moments_by_session=key_moments_by_session,
        )
        reframing_count, reframing_nf, reframing_sr, reframing_dup = self._add_strategic_reframing(
            experiences,
            patterns_detected,
            run_key,
            key_moments_by_session=key_moments_by_session,
        )

        narrative_changes = self._propose_narrative_revision(
            experiences,
            identity,
            patterns_detected,
            key_moments_by_session=key_moments_by_session,
        )

        # R7 Deep — revise stale stances against new evidence.
        stance_outcome = None
        if self._entity_stance_formulator is not None and self._agent_id is not None:
            try:
                stance_outcome = self._entity_stance_formulator.revise_stale(self._agent_id)
            except Exception:  # pragma: no cover - defensive
                stance_outcome = None

        # R9 Deep — formulate typed relations between co-occurring entities.
        relation_outcome = None
        if self._entity_relations_formulator is not None and self._agent_id is not None:
            try:
                relation_outcome = self._entity_relations_formulator.run(self._agent_id)
            except Exception:  # pragma: no cover - defensive
                relation_outcome = None

        # R10 Deep — LLM-resolve similar_entities findings.
        merge_outcome = None
        if self._merge_candidates_handler is not None and self._agent_id is not None:
            try:
                merge_outcome = self._merge_candidates_handler.run(self._agent_id)
            except Exception:  # pragma: no cover - defensive
                merge_outcome = None

        # R11 — feed all collected R5/R7/R9/R10 signals into the identity-
        # revision proposal. Governance / audit still go through R11.5
        # (``IdentityService.apply_self_change``); this is the proposal text.
        identity_changes = self._propose_identity_revision(
            identity,
            patterns_detected,
            health_assessment,
            stance_outcome=stance_outcome,
            relation_outcome=relation_outcome,
            merge_outcome=merge_outcome,
        )

        notes = "outcome=deep_ok"
        if reframing_nf or reframing_sr:
            notes += (
                f" signal=reframing_append_degraded not_found={reframing_nf} "
                f"storage_rejected={reframing_sr}"
            )
        if reframing_dup:
            notes += f" reframing_duplicate_triggered_by={reframing_dup}"
        if stance_outcome is not None and (stance_outcome.formulated or stance_outcome.promoted):
            notes += (
                f" entity_stances_revised={stance_outcome.formulated}"
                f" entity_stances_promoted={stance_outcome.promoted}"
            )
        if merge_outcome is not None and (merge_outcome.merged or merge_outcome.ignored):
            notes += (
                f" merge_candidates_merged={merge_outcome.merged}"
                f" merge_candidates_ignored={merge_outcome.ignored}"
            )
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
        persisted = _read_persisted_event(self.event_store, event)
        _mark_requests_consumed(
            self._reflection_request_queue,
            pending_requests,
            persisted,
            self._clock.now(),
        )
        return persisted

    def _perform_health_assessment(
        self,
        identity: Identity,
        experiences: list[SessionExperience],
        run_key: str,
        *,
        key_moments_by_session: dict[UUID, list[KeyMoment]] | None = None,
    ) -> HealthAssessment:
        """Perform health assessment on 6 Jahoda criteria."""
        criteria: dict[JahodaCriterion, CriterionAssessment] = {}

        for criterion in JahodaCriterion:
            hc = self.reflection_model.assess_health_criterion(
                identity=identity,
                experiences=experiences,
                criterion=criterion,
                key_moments_by_session=key_moments_by_session,
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
        key_moments_by_session: dict[UUID, list[KeyMoment]] | None = None,
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
                experiences=experiences,
                context=context,
                key_moments_by_session=key_moments_by_session,
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
        *,
        key_moments_by_session: dict[UUID, list[KeyMoment]] | None = None,
    ) -> tuple[int, int, int, int]:
        """Add strategic reframing; return (stored, not_found, storage_rejected, duplicate_triggered_by)."""
        return _apply_reframing_notes(
            reflection_model=self.reflection_model,
            session_repo=self.session_repo,
            experiences=experiences,
            patterns=patterns,
            run_key=run_key,
            max_experiences=3,
            key_moments_by_session=key_moments_by_session,
        )

    def _propose_narrative_revision(
        self,
        experiences: list[SessionExperience],
        identity: Identity,
        patterns: list[PatternCandidate],
        *,
        key_moments_by_session: dict[UUID, list[KeyMoment]] | None = None,
    ) -> str:
        """Propose revisions to narrative based on patterns."""
        narrative = self.narrative_repo.get_current()
        if not narrative:
            return "No narrative to revise"

        proposed = self.reflection_model.propose_narrative_update(
            current_narrative=narrative,
            recent_experiences=experiences,
            reflection_level=ReflectionLevel.DEEP,
            key_moments_by_session=key_moments_by_session,
        )

        return proposed.body

    def _propose_identity_revision(
        self,
        identity: Identity,
        patterns: list[PatternCandidate],
        health: HealthAssessment,
        *,
        stance_outcome: object | None = None,
        relation_outcome: object | None = None,
        merge_outcome: object | None = None,
        triage_outcome: object | None = None,
    ) -> str:
        """
        Propose revisions to identity from patterns, health, and (R11) the
        v3 signals from R5/R6/R7/R8/R9/R10 hooks.

        Existing pattern-driven proposals (``potential_habit`` / ``potential_principle``)
        continue to work because aggregators (R5/R6) write through ``PatternStore``
        like the LLM-driven detection. The R11 additions:

        - ``growth_indicator`` / ``agency_level`` marker patterns surface as
          explicit "growth observed" / "agency shift" proposals so the
          downstream governance (R11.5 ``IdentityService.apply_self_change``)
          can decide whether to lift them into ``core_values``.
        - Persistent ``entity_stance`` formulations (R7) appearing repeatedly
          across a period flag "candidate principle: hold this stance" — the
          principle text is **not** invented here; the proposal points the
          operator at the stance for human / advisor review.
        - ``FindingsTriage`` (R8) outcomes are recorded for completeness so
          the audit trail (R11.5) explains *why* a proposal landed.
        - ``MergeCandidatesHandler`` (R10) outcomes likewise.
        - ``EntityRelationsFormulator`` (R9) outcomes likewise.

        Identity is **not** written here — this returns a free-form proposal
        string that the existing governance path (R11.5
        ``IdentityService.apply_self_change`` with audit via
        ``SelfAppliedChangeStore``) consumes.
        """
        proposals: list[str] = []

        for pattern in patterns:
            if pattern.potential_habit:
                proposals.append(f"New habit: {pattern.potential_habit}")
            if pattern.potential_principle:
                proposals.append(f"New principle: {pattern.potential_principle}")

        # R5/R11 — marker-driven growth signals surface as explicit proposals
        # for identity governance to weigh.
        for pattern in patterns:
            desc = pattern.description or ""
            if "'growth_indicator'='progress'" in desc or "growth_indicator=progress" in desc:
                proposals.append(
                    "Growth observed across the period — consider promoting "
                    "the related principle to core."
                )
            elif "'growth_indicator'='regression'" in desc or "growth_indicator=regression" in desc:
                proposals.append(
                    "Regression on growth_indicator across the period — "
                    "review what context produced the regression."
                )
            if "'agency_level'='high'" in desc:
                proposals.append(
                    "High agency level recurring — surface an explicit principle about ownership."
                )
            elif "'agency_level'='low'" in desc:
                proposals.append(
                    "Low agency level recurring — review whether external "
                    "pressures eroded autonomy."
                )

        # R7 — recurring stance formulation across the window is a candidate
        # for principle promotion. We don't invent the principle text; we
        # point the operator at the stance count.
        if stance_outcome is not None:
            f = getattr(stance_outcome, "formulated", 0)
            p = getattr(stance_outcome, "promoted", 0)
            if p:
                proposals.append(
                    f"{p} stance(s) re-affirmed and promoted to non-provisional — "
                    "consider lifting matching stances into core principles."
                )
            elif f >= 3:
                proposals.append(
                    f"{f} new entity stances formulated this period — review "
                    "whether any belong in identity (governance / R11.5)."
                )

        # R9 — newly formulated relations are not identity-relevant per se,
        # but a burst signals a structural shift worth noting in the audit.
        if relation_outcome is not None:
            f = getattr(relation_outcome, "formulated", 0)
            if f >= 3:
                proposals.append(
                    f"{f} new entity relations formulated — verify they "
                    "don't contradict existing principles."
                )

        # R10 — merges may have collapsed entity references that
        # historically grounded principles; flag for review.
        if merge_outcome is not None:
            m = getattr(merge_outcome, "merged", 0)
            if m:
                proposals.append(
                    f"{m} entity merge(s) this period — re-verify principles "
                    "previously grounded in the merged entities."
                )

        # R8 — record what level-B findings the system has chosen not to fix.
        # This is bookkeeping, not a proposal, but it belongs in the audit
        # trail so identity revisions are explainable.
        if triage_outcome is not None:
            attn = getattr(triage_outcome, "requires_attention_count", 0)
            if attn:
                proposals.append(
                    f"{attn} validation finding(s) need operator attention — "
                    "deferring identity-level inferences that depend on them."
                )

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
        return _save_and_get_event(self.event_store, event)

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
        return _save_and_get_event(self.event_store, event)
