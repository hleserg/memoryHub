"""
Session Manager - the session runtime that experiences sessions in real-time.

This is not a data packager - this is an active participant in experience.
Session Manager:
1. Loads personality context at session start
2. Tracks events and key moments during session
3. Colors experience in real-time (not retrospectively)
4. Transfers already-colored experience to Experience Store
5. Creates eigenstate at session end

Critical design principle:
- Experience is colored IN THE MOMENT, not guessed later
- If coloring is incomplete, use incomplete_coloring flag
- Session Manager doesn't fabricate emotions - it records what was actually experienced
"""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID, uuid5

from atman.core.clock_impl import SystemClock
from atman.core.exceptions import (
    SessionAlreadyFinishedError,
    SessionNotFoundError,
    TooManyActiveSessionsError,
)
from atman.core.models import (
    ActiveSessionSummary,
    Eigenstate,
    ExperienceRecord,
    KeyMoment,
    KeyMomentInput,
    SessionContext,
    SessionEvent,
    SessionExperience,
    SessionResult,
)
from atman.core.ports.clock import ClockPort
from atman.core.ports.state_store import StateStore

if TYPE_CHECKING:
    from atman.affect.detector import AffectDetector, AffectDetectorConfig

# Cap for eigenstate list fields; order is insertion-derived until salience ranking exists.
MAX_EIGENSTATE_ITEMS = 5

# Stable SessionExperience.id per session so ``finish_session`` retries do not duplicate records.
_SESSION_EXPERIENCE_ID_NS = UUID("018e5a2b-7c3d-7b2a-9f01-2a3b4c5d6e7f")

_NARRATIVE_SAVE_RETRIES = 5

_LOG = logging.getLogger(__name__)


def _session_finish_marker(session_id: UUID) -> str:
    """Hidden marker so a successful narrative write is not duplicated on finish retry."""
    return f"<!-- atman:session-finish:{session_id} -->"


def deterministic_session_experience_id(session_id: UUID) -> UUID:
    """Return the canonical ExperienceRecord id for a finished session."""
    return uuid5(_SESSION_EXPERIENCE_ID_NS, str(session_id))


class SessionManager:
    """
    Session runtime that experiences sessions in real-time.

    Manages the complete session lifecycle:
    - start_session: loads personality context
    - record_event: tracks raw events and schedules AffectDetector (when configured)
    - append_key_moment / append_key_moment_input: programmatic key moments
    - finish_session: creates SessionExperience + Eigenstate
    """

    def __init__(
        self,
        state_store: StateStore,
        max_active_sessions: int | None = None,
        clock: ClockPort | None = None,
        affect_workspace: Path | None = None,
        affect_config: AffectDetectorConfig | None = None,
    ) -> None:
        """
        Initialize Session Manager.

        Args:
            state_store: Storage for identity, narrative, experience, eigenstate
            max_active_sessions: If set, ``start_session`` raises when this many sessions are active.
            clock: Clock for reproducible timestamps (defaults to SystemClock)
            affect_workspace: Optional workspace directory for affect baseline JSONL
            affect_config: Optional :class:`AffectDetectorConfig` (requires ``affect_workspace``)
        """
        self._state_store = state_store
        self._max_active_sessions = max_active_sessions
        self._clock = clock or SystemClock()
        self._active_sessions: dict[UUID, SessionResult] = {}
        self._lock = threading.Lock()
        self._affect_detector: AffectDetector | None = None
        if affect_workspace is not None and affect_config is not None:
            from atman.affect.detector import AffectDetector

            self._affect_detector = AffectDetector(
                affect_config,
                workspace=affect_workspace,
                append_moment=self.append_key_moment,
            )

    @property
    def affect_detector(self) -> AffectDetector | None:
        """Optional behavioural detector wired to :meth:`append_key_moment`."""
        return self._affect_detector

    def start_session(self, agent_id: UUID) -> SessionContext:
        """
        Start a new session with personality context.

        Loads and creates:
        1. Current identity
        2. Identity snapshot for provenance tracking
        3. Current narrative
        4. Emotional baseline from identity
        5. Last eigenstate (if exists)
        6. Recent reflections summary (placeholder for now)

        The identity snapshot establishes provenance chain: later Reflection/Identity
        can link session experience to the specific identity state that was active
        during the session.

        Args:
            agent_id: UUID of the agent

        Returns:
            SessionContext: Context for this session with identity_snapshot_id

        Raises:
            ValueError: If identity or narrative not found
            TooManyActiveSessionsError: If active session limit is exceeded
        """
        identity = self._state_store.load_identity(agent_id)
        if identity is None:
            raise ValueError(f"Identity not found for agent {agent_id}")

        narrative = self._state_store.load_narrative(identity.id)
        if narrative is None:
            raise ValueError(f"Narrative not found for identity {identity.id}")

        last_eigenstate = self._state_store.load_latest_eigenstate(identity_id=identity.id)

        from atman.core.models.identity import IdentitySnapshot

        context = SessionContext(
            identity=identity,
            identity_snapshot_id=None,
            narrative=narrative,
            emotional_baseline=identity.emotional_baseline,
            last_eigenstate=last_eigenstate,
            recent_reflections_summary="",  # Placeholder for future
        )

        with self._lock:
            if self._max_active_sessions is not None and len(self._active_sessions) >= (
                self._max_active_sessions
            ):
                raise TooManyActiveSessionsError(
                    f"Active session limit ({self._max_active_sessions}) reached; "
                    "finish a session before starting another."
                )
            snapshot = IdentitySnapshot(
                identity_id=identity.id,
                description="Session start snapshot",
                identity_snapshot=identity,
                change_summary="Snapshot for session lifecycle tracking",
            )
            stored_snapshot = self._state_store.create_identity_snapshot(snapshot)
            context = context.model_copy(update={"identity_snapshot_id": stored_snapshot.id})
            self._active_sessions[context.session_id] = SessionResult(
                session_id=context.session_id,
                started_at=context.started_at,
                events=[],
                key_moments=[],
                identity_snapshot_id=stored_snapshot.id,
                identity_id=identity.id,
            )

        return context

    def record_event(self, session_id: UUID, event: SessionEvent) -> None:
        """
        Record an event from lower agent during session.

        Not all events become key moments - this is just tracking what happened.

        Args:
            session_id: UUID of the session
            event: Event to record

        Raises:
            SessionNotFoundError: If session not found
            SessionAlreadyFinishedError: If session already finished
        """
        event_copy = event.model_copy(update={"session_id": session_id})
        with self._lock:
            session_result = self._active_sessions.get(session_id)
            if session_result is None:
                raise SessionNotFoundError(f"Session {session_id} not found")
            if session_result.is_finished:
                raise SessionAlreadyFinishedError(f"Session {session_id} already finished")
            session_result.events.append(event_copy)
        self._schedule_affect_processing(session_id, event_copy)

    def _schedule_affect_processing(self, session_id: UUID, event: SessionEvent) -> None:
        """Schedule :class:`AffectDetector` after ``record_event``.

        With a running asyncio loop this is fire-and-forget via ``create_task``.
        Without a loop, ``asyncio.run`` executes the detector synchronously on this
        thread (blocking until scoring finishes) — avoid configuring affect for
        latency-sensitive synchronous ``record_event`` callers without an event loop.
        """
        det = self._affect_detector
        if det is None:
            return
        text = event.description
        thinking = event.thinking

        async def _run() -> None:
            try:
                await det.process(text, thinking=thinking, session_id=session_id)
            except Exception:
                _LOG.exception("AffectDetector.process failed for session %s", session_id)

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_run())  # noqa: RUF006 — fire-and-forget affect hook
        except RuntimeError:
            try:
                asyncio.run(_run())
            except RuntimeError:
                _LOG.warning(
                    "AffectDetector could not be scheduled (no usable event loop); session_id=%s",
                    session_id,
                )

    def append_key_moment(self, session_id: UUID, moment: KeyMoment) -> None:
        """
        Append a fully materialised key moment (used by AffectDetector and tests).

        Raises:
            SessionNotFoundError: If session not found
            SessionAlreadyFinishedError: If session already finished
        """
        with self._lock:
            session_result = self._active_sessions.get(session_id)
            if session_result is None:
                raise SessionNotFoundError(f"Session {session_id} not found")
            if session_result.is_finished:
                raise SessionAlreadyFinishedError(f"Session {session_id} already finished")
            session_result.key_moments.append(moment)

    def append_key_moment_input(self, session_id: UUID, moment: KeyMomentInput) -> None:
        """
        Validate :class:`KeyMomentInput` and append the resulting :class:`KeyMoment`.

        This replaces the removed :meth:`record_key_moment` for programmatic callers.
        """
        with self._lock:
            session_result = self._active_sessions.get(session_id)
            if session_result is None:
                raise SessionNotFoundError(f"Session {session_id} not found")
            if session_result.is_finished:
                raise SessionAlreadyFinishedError(f"Session {session_id} already finished")

            if (
                moment.emotional_valence == 0.0
                and moment.emotional_intensity == 0.0
                and not moment.incomplete_coloring
            ):
                raise ValueError(
                    "Key moment has no emotional coloring. "
                    "If coloring couldn't be captured, set incomplete_coloring=True"
                )

            moment_with_time = moment.model_copy(update={"recorded_at": self._clock.now()})
            key_moment = moment_with_time.to_key_moment()

            if moment.incomplete_coloring:
                session_result.incomplete_coloring = True

            session_result.key_moments.append(key_moment)

    def record_key_moment(self, session_id: UUID, moment: KeyMomentInput) -> None:
        """
        Removed — use :class:`~atman.affect.detector.AffectDetector` or
        :meth:`append_key_moment_input`.
        """
        _ = (session_id, moment)
        raise AttributeError(
            "SessionManager.record_key_moment was removed. Use AffectDetector.submit_self_report "
            "for agent-authored key moments, or append_key_moment / append_key_moment_input for "
            "programmatic recording. See atman.affect.AffectDetector."
        )

    def _note_facts_read(self, session_id: UUID, fact_ids: list[UUID]) -> None:
        """
        Note that specific facts were read/accessed during this session.

        This creates back-links from experiences to the facts that shaped them.
        Called automatically when facts are surfaced to the session context.

        Args:
            session_id: UUID of the session
            fact_ids: List of fact IDs that were read

        Raises:
            SessionNotFoundError: If session not found
            SessionAlreadyFinishedError: If session already finished
        """
        with self._lock:
            session_result = self._active_sessions.get(session_id)
            if session_result is None:
                raise SessionNotFoundError(f"Session {session_id} not found")
            if session_result.is_finished:
                raise SessionAlreadyFinishedError(f"Session {session_id} already finished")

            # Store fact IDs in the SessionResult PrivateAttr for aggregation at finish.
            session_result._facts_read.update(fact_ids)

    def finish_session(
        self,
        session_id: UUID,
        overall_emotional_tone: float = 0.0,
        key_insight: str = "",
        alignment_check: bool = True,
        alignment_notes: str = "",
    ) -> SessionResult:
        """
        Finish session and create SessionExperience + Eigenstate + update Narrative.

        This method:
        1. Validates session can be finished (has key moments)
        2. Creates SessionExperience from key moments
        3. Stores experience in Experience Store
        4. Creates and stores Eigenstate
        5. Updates recent narrative layer with session summary
        6. Removes session from active tracking
        7. Returns SessionResult

        The narrative update ensures the next start_session() loads updated context,
        fulfilling the minimal runtime path requirement: session result → narrative update
        → next session sees updated self-narrative.

        Args:
            session_id: UUID of the session
            overall_emotional_tone: Overall emotional tone (-1.0 to 1.0)
            key_insight: Main insight from session
            alignment_check: Did experience match identity?
            alignment_notes: Notes about alignment or drift

        Returns:
            SessionResult: Complete session result with experience and eigenstate

        Raises:
            SessionNotFoundError: If session not found
            SessionAlreadyFinishedError: If session was already finished
            ValueError: If session has no key moments, tone out of range, or alignment contract
        """
        with self._lock:
            session_result = self._active_sessions.get(session_id)
            if session_result is None:
                raise SessionNotFoundError(f"Session {session_id} not found")
            if session_result.is_finished:
                raise SessionAlreadyFinishedError(f"Session {session_id} already finished")
            if not session_result.key_moments:
                raise ValueError("Cannot finish session without key moments")
            if not -1.0 <= overall_emotional_tone <= 1.0:
                raise ValueError("overall_emotional_tone must be between -1.0 and 1.0")
            if not alignment_check and not alignment_notes.strip():
                raise ValueError(
                    "alignment_notes is required when alignment_check=False "
                    "(explain how experience diverged from identity)."
                )
            # Mark as finishing to block concurrent finish_session calls
            # If persistence fails, we rollback this flag in except
            session_result.is_finished = True

        session_result.finished_at = self._clock.now()
        session_result.overall_emotional_tone = overall_emotional_tone
        session_result.key_insight = key_insight
        session_result.alignment_check = alignment_check
        session_result.alignment_notes = alignment_notes

        experience_id = deterministic_session_experience_id(session_id)

        # Persist experience, eigenstate, and update narrative
        # If this fails, rollback is_finished flag to allow retry
        try:
            existing_record = self._state_store.get_experience(experience_id)
            if existing_record is None:
                # Store key moments separately first
                self._state_store.store_key_moments(session_id, session_result.key_moments)

                # Aggregate fact_refs from all key moments and _note_facts_read
                fact_refs_set: set[UUID] = set()
                for moment in session_result.key_moments:
                    fact_refs_set.update(moment.fact_refs)
                # Also include any facts noted via _note_facts_read
                fact_refs_set.update(session_result._facts_read)

                # Extract key moment IDs and compute salience metadata
                key_moment_ids = [moment.id for moment in session_result.key_moments]

                # Compute avg_emotional_intensity and has_profound_moment
                avg_emotional_intensity = 0.5  # default
                has_profound_moment = False
                if session_result.key_moments:
                    from atman.core.models.experience import EmotionalDepth

                    avg_emotional_intensity = sum(
                        m.how_i_felt.emotional_intensity for m in session_result.key_moments
                    ) / len(session_result.key_moments)
                    has_profound_moment = any(
                        m.how_i_felt.depth == EmotionalDepth.PROFOUND
                        for m in session_result.key_moments
                    )

                experience = SessionExperience(
                    id=experience_id,
                    session_id=session_id,
                    timestamp=session_result.finished_at,
                    key_moment_ids=key_moment_ids,
                    recorded_by="session_manager",
                    identity_snapshot_id=session_result.identity_snapshot_id,
                    importance=0.5,
                    salience=0.5,
                    avg_emotional_intensity=avg_emotional_intensity,
                    has_profound_moment=has_profound_moment,
                    incomplete_coloring=session_result.incomplete_coloring,
                    fact_refs=list(fact_refs_set),
                )
                experience_record = ExperienceRecord(experience=experience)
                self._state_store.create_experience(experience_record)
            else:
                if existing_record.experience.session_id != session_id:
                    raise ValueError(
                        f"Stored experience {experience_id} belongs to another session "
                        f"({existing_record.experience.session_id}); refusing to proceed."
                    )

            eigenstate = self._create_eigenstate(session_result)
            session_result.eigenstate = eigenstate
            self._state_store.save_eigenstate(eigenstate)

            self._save_session_narrative_update(session_result)

        except Exception:
            # Rollback is_finished flag to allow retry of finish_session()
            with self._lock:
                session_result.is_finished = False
            raise

        # Remove from active sessions only after successful persistence
        with self._lock:
            self._active_sessions.pop(session_id, None)

        return session_result.model_copy(deep=True)

    def _save_session_narrative_update(self, session_result: SessionResult) -> None:
        """Append session summary to recent narrative with optimistic concurrency."""
        if session_result.identity_id is None:
            return
        identity_id = session_result.identity_id
        marker = _session_finish_marker(session_result.session_id)
        last_err: BaseException | None = None
        for _ in range(_NARRATIVE_SAVE_RETRIES):
            narrative = self._state_store.load_narrative(identity_id)
            if narrative is None:
                raise RuntimeError(
                    f"Narrative disappeared for identity {identity_id} during finish_session; "
                    "session experience/eigenstate saved but narrative not updated. "
                    "This breaks the session lifecycle contract."
                )
            if marker in narrative.recent_layer.content:
                return
            update_text = f"{self._build_narrative_update(session_result)}\n{marker}"
            existing_content = narrative.recent_layer.content.strip()
            next_content = (
                f"{existing_content}\n\n{update_text}" if existing_content else update_text
            )
            expected_at = narrative.updated_at
            narrative.update_recent_layer(next_content)
            try:
                self._state_store.save_narrative(
                    narrative,
                    expected_updated_at=expected_at,
                )
                return
            except ValueError as exc:
                msg = str(exc)
                if "updated_at mismatch" in msg:
                    last_err = exc
                    continue
                raise
        raise RuntimeError(
            "Narrative concurrent update: exceeded retries; resolve conflict outside SessionManager."
        ) from last_err

    def _build_narrative_update(self, session_result: SessionResult) -> str:
        """
        Build narrative update from session result.

        Creates a brief summary of the session for the recent narrative layer.
        This ensures the agent's self-narrative reflects recent lived experience.

        Args:
            session_result: Finished session result

        Returns:
            str: Narrative update text
        """
        # Extract key themes from session
        themes = set()
        for moment in session_result.key_moments:
            themes.update(moment.values_touched)

        # Build summary
        parts = []

        if session_result.key_insight:
            parts.append(f"Recently: {session_result.key_insight}")

        if themes:
            themes_str = ", ".join(sorted(themes)[:5])  # Limit to 5 themes
            parts.append(f"This engaged my values around {themes_str}.")

        if session_result.key_moments:
            num_moments = len(session_result.key_moments)
            tone = session_result.overall_emotional_tone
            tone_desc = "positive" if tone > 0.2 else "negative" if tone < -0.2 else "neutral"
            parts.append(
                f"Experienced {num_moments} significant moment{'s' if num_moments > 1 else ''} "
                f"with an overall {tone_desc} emotional tone."
            )

        if not parts:
            parts.append("Recently completed a session.")

        return " ".join(parts)

    def _create_eigenstate(self, session_result: SessionResult) -> Eigenstate:
        """
        Create eigenstate from session result.

        Open threads, themes, and tensions are truncated to :data:`MAX_EIGENSTATE_ITEMS`
        in encounter order until a salience-based ranking exists.

        Args:
            session_result: Session result to create eigenstate from

        Returns:
            Eigenstate: Created eigenstate
        """
        if session_result.key_moments:
            avg_intensity = sum(
                m.how_i_felt.emotional_intensity for m in session_result.key_moments
            ) / len(session_result.key_moments)
        else:
            avg_intensity = 0.5

        n_events = len(session_result.events)
        cognitive_load = min(1.0, float(n_events) / 10.0)

        open_threads_raw = [
            e.description
            for e in session_result.events
            if e.event_type in ("unfinished", "open_question", "pending")
        ]
        open_threads = list(dict.fromkeys(open_threads_raw))

        dominant_flat = [
            value for moment in session_result.key_moments for value in moment.values_touched
        ]
        dominant_themes = list(dict.fromkeys(dominant_flat))

        tension_flat = [
            principle
            for moment in session_result.key_moments
            for principle in moment.principles_questioned
        ]
        unresolved_tensions = list(dict.fromkeys(tension_flat))

        # Deterministic ID based on session_id for idempotent retry
        eigenstate_id = UUID(int=session_result.session_id.int ^ 0xE16E157A7E)

        return Eigenstate(
            id=eigenstate_id,
            session_id=session_result.session_id,
            identity_id=session_result.identity_id,
            timestamp=session_result.finished_at,
            emotional_tone=session_result.overall_emotional_tone,
            emotional_intensity=avg_intensity,
            cognitive_load=cognitive_load,
            open_threads=open_threads[:MAX_EIGENSTATE_ITEMS],
            dominant_themes=dominant_themes[:MAX_EIGENSTATE_ITEMS],
            unresolved_tensions=unresolved_tensions[:MAX_EIGENSTATE_ITEMS],
            session_summary=session_result.key_insight or "Session completed",
            key_insight=session_result.key_insight,
        )

    def get_active_session(self, session_id: UUID) -> SessionResult | None:
        """
        Get active session by ID.

        Sessions mid-finish (``is_finished``) are not returned as active.

        Args:
            session_id: UUID of the session

        Returns:
            SessionResult | None: Session result if active and not finishing, None otherwise
        """
        with self._lock:
            session_result = self._active_sessions.get(session_id)
            if session_result is None or session_result.is_finished:
                return None
            return session_result.model_copy(deep=True)

    def list_active_sessions(self) -> list[ActiveSessionSummary]:
        """
        List active sessions with counts (avoids N+1 ``get_active_session`` calls).

        Returns:
            Summaries for sessions that are not mid-finish.
        """
        with self._lock:
            return [
                ActiveSessionSummary(
                    session_id=sid,
                    started_at=sr.started_at,
                    events_count=len(sr.events),
                    key_moments_count=len(sr.key_moments),
                )
                for sid, sr in self._active_sessions.items()
                if not sr.is_finished
            ]
