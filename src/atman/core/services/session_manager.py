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
import json
import logging
import threading
from pathlib import Path
from typing import IO, TYPE_CHECKING, Literal, cast
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
        workspace: Path | None = None,
    ) -> None:
        """
        Initialize Session Manager.

        Args:
            state_store: Storage for identity, narrative, experience, eigenstate
            max_active_sessions: If set, ``start_session`` raises when this many sessions are active.
            clock: Clock for reproducible timestamps (defaults to SystemClock)
            affect_workspace: Optional workspace directory for affect baseline JSONL
            affect_config: Optional :class:`AffectDetectorConfig` (requires ``affect_workspace``)
            workspace: Optional workspace directory for session journals
        """
        self._state_store = state_store
        self._max_active_sessions = max_active_sessions
        self._clock = clock or SystemClock()
        self._active_sessions: dict[UUID, SessionResult] = {}
        self._journal_locks: dict[UUID, IO[str]] = {}
        self._lock = threading.Lock()
        self._workspace = workspace
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

    def _journal_path(self, agent_id: UUID, session_id: UUID) -> Path | None:
        """Return journal path for a session, or None if workspace not configured."""
        if self._workspace is None:
            return None
        sessions_dir = self._workspace / str(agent_id) / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        return sessions_dir / f"active_{session_id}.jsonl"

    def _journal_lock_path(self, agent_id: UUID, session_id: UUID) -> Path | None:
        """Return lock path for an active session journal."""
        journal_path = self._journal_path(agent_id, session_id)
        if journal_path is None:
            return None
        return journal_path.with_suffix(f"{journal_path.suffix}.lock")

    def _try_lock_journal(self, agent_id: UUID, session_id: UUID) -> IO[str] | None:
        """Try to take the inter-process lock for a session journal."""
        lock_path = self._journal_lock_path(agent_id, session_id)
        if lock_path is None:
            return None

        lock_file: IO[str] | None = None
        try:
            import fcntl

            lock_file = lock_path.open("a+", encoding="utf-8")
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return lock_file
        except BlockingIOError:
            if lock_file is not None:
                lock_file.close()
            return None
        except (ImportError, OSError) as exc:
            _LOG.warning("Failed to lock journal for session %s: %s", session_id, exc)
            return None

    def _release_journal_file(self, lock_file: IO[str], *, unlink: bool) -> None:
        """Release a journal lock file."""
        lock_path = Path(lock_file.name)
        try:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        except (ImportError, OSError) as exc:
            _LOG.warning("Failed to unlock journal %s: %s", lock_path, exc)
        finally:
            lock_file.close()
            if unlink:
                lock_path.unlink(missing_ok=True)

    def _journal_locked_elsewhere(self, agent_id: UUID, session_id: UUID) -> bool:
        """Return True when another live process owns this session journal."""
        lock_file = self._try_lock_journal(agent_id, session_id)
        if lock_file is None:
            return self._workspace is not None
        self._release_journal_file(lock_file, unlink=False)
        return False

    def _write_journal_entry(
        self, agent_id: UUID, session_id: UUID, entry: dict[str, object]
    ) -> None:
        """Append journal entry to session journal (if workspace configured)."""
        journal_path = self._journal_path(agent_id, session_id)
        if journal_path is None:
            return
        try:
            with journal_path.open("a", encoding="utf-8") as f:
                json.dump(entry, f, default=str)
                f.write("\n")
        except (OSError, ValueError) as exc:
            _LOG.warning("Failed to write journal entry for session %s: %s", session_id, exc)

    # PLAYBOOK-START
    # id: self-contained-recovery-journals
    # category: design-patterns
    # title: Self-Contained Recovery Journals for In-Flight State
    # status: draft
    # since: 2026-05-12
    #
    # Pattern: when journaling in-flight state for crash recovery, include enough
    # payload to reconstruct the referenced records, not just their IDs. Recovery
    # must refuse to delete the journal if it cannot rebuild every referenced row.
    #
    # Why generalizable: any write-behind or finish-time persistence flow can crash
    # between "record exists in memory" and "record exists in durable storage".
    # ID-only journals create dangling references; self-contained journal entries
    # preserve the last recovery source.
    #
    # Trade-offs: journal entries are larger and may duplicate data already stored
    # on the happy path, but the duplication is bounded and only used for recovery.
    # PLAYBOOK-END
    def _recover_orphaned_sessions(self, agent_id: UUID) -> None:
        """
        Scan for orphaned session journals and convert to SessionExperience.

        Orphaned journals are from interrupted sessions that didn't complete finish_session.
        Each orphan is converted to a SessionExperience with close_reason="interrupted".
        """
        if self._workspace is None:
            return
        sessions_dir = self._workspace / str(agent_id) / "sessions"
        if not sessions_dir.exists():
            return

        for journal_file in sessions_dir.glob("active_*.jsonl"):
            try:
                # Extract session_id from filename: active_{session_id}.jsonl
                session_id_str = journal_file.stem.replace("active_", "")
                session_id = UUID(session_id_str)

                # Skip journals for currently active sessions (not orphans)
                with self._lock:
                    if session_id in self._active_sessions:
                        continue
                if self._journal_locked_elsewhere(agent_id, session_id):
                    _LOG.debug("Skipping live journal locked by another process: %s", session_id)
                    continue

                # Compute deterministic experience_id
                experience_id = deterministic_session_experience_id(session_id)

                # Check if experience already exists in StateStore
                existing_exp = self._state_store.get_experience(experience_id)
                if existing_exp is not None:
                    # Already saved - journal is stale, just delete it
                    journal_file.unlink()
                    _LOG.info("Deleted stale journal for session %s", session_id)
                    continue

                # Parse journal to extract key moments and facts
                key_moment_ids: list[UUID] = []
                journaled_moments: dict[UUID, KeyMoment] = {}
                fact_refs_set: set[UUID] = set()

                with journal_file.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                            if entry.get("type") == "key_moment":
                                moment_id = UUID(entry["moment_id"])
                                key_moment_ids.append(moment_id)
                                moment_data = entry.get("moment")
                                if isinstance(moment_data, dict):
                                    journaled_moments[moment_id] = KeyMoment.model_validate(
                                        moment_data
                                    )
                                # Extract fact_refs if present
                                for fact_id_str in entry.get("fact_refs", []):
                                    fact_refs_set.add(UUID(fact_id_str))
                            elif entry.get("type") == "facts_read":
                                for fact_id_str in entry.get("fact_ids", []):
                                    fact_refs_set.add(UUID(fact_id_str))
                        except (json.JSONDecodeError, KeyError, ValueError) as exc:
                            _LOG.warning(
                                "Skipping malformed journal line in %s: %s", journal_file, exc
                            )
                            continue

                # If we have key moments, create SessionExperience
                if key_moment_ids:
                    # Try to load actual KeyMoment objects from storage for better metadata
                    loaded_moments: list[KeyMoment] = []
                    for moment_id in key_moment_ids:
                        loaded_moment = self._state_store.get_key_moment(moment_id)
                        if loaded_moment is None and moment_id in journaled_moments:
                            loaded_moment = journaled_moments[moment_id]
                            try:
                                self._state_store.create_key_moment(loaded_moment)
                            except ValueError:
                                # Another recovery/finish path stored it first.
                                loaded_moment = self._state_store.get_key_moment(moment_id)
                        if loaded_moment is not None:
                            loaded_moments.append(loaded_moment)

                    if len(loaded_moments) != len(key_moment_ids):
                        _LOG.warning(
                            "Cannot recover orphaned session %s: %d/%d key moments available; "
                            "leaving journal for manual recovery",
                            session_id,
                            len(loaded_moments),
                            len(key_moment_ids),
                        )
                        continue

                    # Compute better metadata if we have loaded moments
                    avg_emotional_intensity = 0.5
                    has_profound_moment = False
                    if loaded_moments:
                        from atman.core.models.experience import EmotionalDepth

                        avg_emotional_intensity = sum(
                            m.how_i_felt.emotional_intensity for m in loaded_moments
                        ) / len(loaded_moments)
                        has_profound_moment = any(
                            m.how_i_felt.depth == EmotionalDepth.PROFOUND for m in loaded_moments
                        )

                    experience = SessionExperience(
                        id=experience_id,
                        session_id=session_id,
                        timestamp=self._clock.now(),
                        key_moment_ids=key_moment_ids,
                        recorded_by="session_manager_recovery",
                        identity_snapshot_id=None,  # Unknown for orphaned sessions
                        importance=0.5,
                        salience=0.5,
                        avg_emotional_intensity=avg_emotional_intensity,
                        has_profound_moment=has_profound_moment,
                        incomplete_coloring=True,  # Orphaned sessions didn't complete proper coloring
                        fact_refs=list(fact_refs_set),
                        close_reason="interrupted",
                        restart_reason="",
                        agent_recap=None,
                    )
                    experience_record = ExperienceRecord(experience=experience)
                    self._state_store.create_experience(experience_record)
                    _LOG.info(
                        "Recovered orphaned session %s with %d key moments (%d loaded from storage)",
                        session_id,
                        len(key_moment_ids),
                        len(loaded_moments),
                    )

                # Delete journal after successful recovery (or if no key moments)
                journal_file.unlink()

            except Exception as exc:
                _LOG.error("Failed to recover orphaned journal %s: %s", journal_file, exc)
                continue

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

        Also scans for orphaned session journals (from interrupted sessions)
        and converts them to SessionExperience with close_reason="interrupted".

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
        # Recover orphaned sessions before starting new one
        self._recover_orphaned_sessions(agent_id)

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

        journal_lock = self._try_lock_journal(identity.id, context.session_id)
        if journal_lock is not None:
            with self._lock:
                self._journal_locks[context.session_id] = journal_lock

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

            # Get agent_id for journal
            agent_id = session_result.identity_id

        # Write to journal after releasing lock
        if agent_id is not None:
            self._write_journal_entry(
                agent_id,
                session_id,
                {
                    "type": "key_moment",
                    "moment_id": str(moment.id),
                    "timestamp": self._clock.now().isoformat(),
                    "what_happened": moment.what_happened,
                    "moment": moment.model_dump(mode="json"),
                    "fact_refs": [str(fid) for fid in moment.fact_refs],
                },
            )

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

            # Write journal entry (outside lock to avoid blocking)
            agent_id = session_result.identity_id

        # Write to journal after releasing lock
        if agent_id is not None:
            self._write_journal_entry(
                agent_id,
                session_id,
                {
                    "type": "key_moment",
                    "moment_id": str(key_moment.id),
                    "timestamp": self._clock.now().isoformat(),
                    "what_happened": key_moment.what_happened,
                    "moment": key_moment.model_dump(mode="json"),
                    "fact_refs": [str(fid) for fid in key_moment.fact_refs],
                },
            )

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

            # Get agent_id for journal
            agent_id = session_result.identity_id

        # Write to journal after releasing lock
        if agent_id is not None and fact_ids:
            self._write_journal_entry(
                agent_id,
                session_id,
                {
                    "type": "facts_read",
                    "timestamp": self._clock.now().isoformat(),
                    "fact_ids": [str(fid) for fid in fact_ids],
                },
            )

    def finish_session(
        self,
        session_id: UUID,
        overall_emotional_tone: float = 0.0,
        key_insight: str = "",
        alignment_check: bool = True,
        alignment_notes: str = "",
        close_reason: str | None = None,
        restart_reason: str | None = None,
        agent_recap: str | None = None,
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
            close_reason: Reason for session closure (timeout_sleep | restart | forced | interrupted)
            restart_reason: Human-readable reason when close_reason=restart
            agent_recap: Agent's recap before timeout_sleep

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
                # Compute colored_fact_ids (facts referenced in key moments)
                colored_fact_ids: set[UUID] = set()
                for moment in session_result.key_moments:
                    colored_fact_ids.update(moment.fact_refs)

                # Compute unexamined facts (read but not colored)
                unexamined_fact_refs = list(session_result._facts_read - colored_fact_ids)

                # Aggregate all fact_refs (union of colored and unexamined)
                fact_refs_set: set[UUID] = set()
                fact_refs_set.update(colored_fact_ids)
                fact_refs_set.update(session_result._facts_read)

                # Save each KeyMoment via create_key_moment and collect IDs
                # Idempotent: skip if moment already exists (for retry scenarios)
                key_moment_ids: list[UUID] = []
                for moment in session_result.key_moments:
                    if self._state_store.get_key_moment(moment.id) is None:
                        self._state_store.create_key_moment(moment)
                    key_moment_ids.append(moment.id)

                # Also store session association for backward compatibility
                self._state_store.store_key_moments(session_id, session_result.key_moments)

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

                _allowed_close_reasons = (
                    "timeout_sleep",
                    "menu_timeout",
                    "restart",
                    "forced",
                    "interrupted",
                )
                safe_close_reason: (
                    Literal["timeout_sleep", "menu_timeout", "restart", "forced", "interrupted"]
                    | None
                ) = (
                    cast(
                        Literal[
                            "timeout_sleep",
                            "menu_timeout",
                            "restart",
                            "forced",
                            "interrupted",
                        ],
                        close_reason,
                    )
                    if close_reason in _allowed_close_reasons
                    else None
                )

                experience = SessionExperience(
                    id=experience_id,
                    session_id=session_id,
                    timestamp=session_result.finished_at,
                    key_moment_ids=key_moment_ids,
                    unexamined_fact_refs=unexamined_fact_refs,
                    recorded_by="session_manager",
                    identity_snapshot_id=session_result.identity_snapshot_id,
                    importance=0.5,
                    salience=0.5,
                    avg_emotional_intensity=avg_emotional_intensity,
                    has_profound_moment=has_profound_moment,
                    incomplete_coloring=session_result.incomplete_coloring,
                    fact_refs=list(fact_refs_set),
                    close_reason=safe_close_reason,
                    restart_reason=restart_reason or "",  # Convert None to empty string
                    agent_recap=agent_recap,
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
            journal_lock = self._journal_locks.pop(session_id, None)

        # Delete journal after successful persistence
        if session_result.identity_id is not None:
            journal_path = self._journal_path(session_result.identity_id, session_id)
            if journal_path is not None and journal_path.exists():
                try:
                    journal_path.unlink()
                    _LOG.debug("Deleted journal for completed session %s", session_id)
                except OSError as exc:
                    _LOG.warning("Failed to delete journal for session %s: %s", session_id, exc)

        if journal_lock is not None:
            self._release_journal_file(journal_lock, unlink=True)

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
