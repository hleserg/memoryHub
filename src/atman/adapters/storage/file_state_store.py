"""
File-based StateStore implementation.

Stores identity, narrative, and eigenstate in JSON files.
Suitable for local development and single-agent use cases.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from atman.adapters.storage._atomic_write import write_atomically
from atman.core.models import (
    Eigenstate,
    ExperienceRecord,
    Identity,
    IdentitySnapshot,
    KeyMoment,
    NarrativeDocument,
    ReframingNote,
)
from atman.core.models.session import Session
from atman.core.ports.state_store import (
    DateRangeQuery,
    DepthQuery,
    ExperienceQuery,
    FactRefsContainsQuery,
    SessionExperienceQuery,
    StateStore,
    ValuesTouchedQuery,
)


def _read_json_file(path: Path) -> Any:
    """Read JSON from ``path``; raise ``ValueError`` with file context on parse error."""
    raw = path.read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Corrupted JSON in state store file {path}: "
            f"{exc.msg} (line {exc.lineno}, column {exc.colno})"
        ) from exc


class FileStateStore(StateStore):
    """
    File-based implementation of StateStore.

    Storage layout:
    - {workspace}/identity.json - current identity
    - {workspace}/identity_snapshots/ - identity snapshots
    - {workspace}/narrative.json - current narrative
    - {workspace}/narrative_archive/ - archived narratives
    - {workspace}/eigenstate.json - latest eigenstate
    - {workspace}/experiences/ - experience records (from base implementation)
    """

    def __init__(self, workspace: Path):
        """
        Initialize file state store.

        Args:
            workspace: Root directory for state storage
        """
        self.workspace = workspace
        self.workspace.mkdir(parents=True, exist_ok=True)

        # Create subdirectories
        self.identity_snapshots_dir = self.workspace / "identity_snapshots"
        self.identity_snapshots_dir.mkdir(exist_ok=True)

        self.narrative_archive_dir = self.workspace / "narrative_archive"
        self.narrative_archive_dir.mkdir(exist_ok=True)

        self.experiences_dir = self.workspace / "experiences"
        self.experiences_dir.mkdir(exist_ok=True)

        self.key_moments_dir = self.workspace / "key_moments"
        self.key_moments_dir.mkdir(exist_ok=True)

        self.sessions_dir = self.workspace / "sessions"
        self.sessions_dir.mkdir(exist_ok=True)

        # Paths for current state files
        self.identity_path = self.workspace / "identity.json"
        self.narrative_path = self.workspace / "narrative.json"
        self.eigenstate_path = self.workspace / "eigenstate.json"
        self.key_moments_path = self.workspace / "key_moments.jsonl"

    def _write_json_atomically(self, path: Path, content: str) -> None:
        """Write JSON without exposing callers to partially rewritten files.

        Thin wrapper over ``write_atomically``; preserved as a method since
        internal call sites (and possibly subclasses) rely on it.
        """
        write_atomically(path, content)

    # Experience Store operations (minimal implementation)

    def create_experience(self, record: ExperienceRecord) -> ExperienceRecord:
        """Create experience record."""
        experience_file = self.experiences_dir / f"{record.experience.id}.json"
        if experience_file.exists():
            raise ValueError(f"Experience with id {record.experience.id} already exists")
        self._write_json_atomically(experience_file, record.model_dump_json(indent=2))
        return record

    def get_experience(self, experience_id: UUID) -> ExperienceRecord | None:
        """Get experience by ID."""
        experience_file = self.experiences_dir / f"{experience_id}.json"
        if not experience_file.exists():
            return None
        data = _read_json_file(experience_file)
        return ExperienceRecord.model_validate(data)

    def add_reframing_note(
        self, experience_id: UUID, note: ReframingNote
    ) -> ExperienceRecord | None:
        """Add reframing note to experience."""
        record = self.get_experience(experience_id)
        if record is None:
            return None
        if note.triggered_by and any(
            n.triggered_by == note.triggered_by for n in record.experience.reframing_notes
        ):
            return record
        record.experience.reframing_notes.append(note)
        experience_file = self.experiences_dir / f"{experience_id}.json"
        self._write_json_atomically(experience_file, record.model_dump_json(indent=2))
        return record

    def mark_accessed(self, experience_id: UUID) -> ExperienceRecord | None:
        """Mark experience as accessed (legacy)."""
        record = self.get_experience(experience_id)
        if record is None:
            return None
        record.experience.last_accessed_at = datetime.now(UTC)
        record.experience.access_count += 1
        experience_file = self.experiences_dir / f"{experience_id}.json"
        self._write_json_atomically(experience_file, record.model_dump_json(indent=2))
        return record

    def search_experiences(
        self, query: ExperienceQuery | None = None, limit: int = 10
    ) -> list[ExperienceRecord]:
        """Search experiences (basic implementation).

        For moment-aware queries (``ValuesTouchedQuery``, ``DepthQuery``,
        ``FactRefsContainsQuery``) we batch-load all moments for an experience
        in a single read of ``{session_id}_moments.json`` instead of calling
        ``get_key_moment`` once per moment id (HLE-43). The per-moment
        ``{id}.json`` fallback handles moments not present in the session file
        (e.g. created via ``create_key_moment`` without a per-session bundle,
        or belonging to a different session than the experience record).
        """
        all_experiences: list[ExperienceRecord] = []

        for experience_file in self.experiences_dir.glob("*.json"):
            data = _read_json_file(experience_file)
            record = ExperienceRecord.model_validate(data)

            # Apply filter
            if query is None:
                all_experiences.append(record)
            elif isinstance(query, SessionExperienceQuery):
                if record.experience.session_id == query.session_id:
                    all_experiences.append(record)
            elif isinstance(query, ValuesTouchedQuery | DepthQuery | FactRefsContainsQuery):
                moments = self._load_moments_for_record(record)
                if isinstance(query, ValuesTouchedQuery):
                    if any(any(v in m.values_touched for v in query.values) for m in moments):
                        all_experiences.append(record)
                elif isinstance(query, DepthQuery):
                    if any(m.how_i_felt.depth.value == query.depth for m in moments):
                        all_experiences.append(record)
                else:  # FactRefsContainsQuery
                    if any(query.fact_id in m.fact_refs for m in moments):
                        all_experiences.append(record)
            elif (
                isinstance(query, DateRangeQuery)
                and query.start_date <= record.experience.timestamp <= query.end_date
            ):
                all_experiences.append(record)

        # Sort by timestamp descending
        all_experiences.sort(key=lambda r: r.experience.timestamp, reverse=True)
        return all_experiences[:limit]

    def _load_moments_for_record(self, record: ExperienceRecord) -> list[KeyMoment]:
        """Load all key moments referenced by ``record`` with a single batched read.

        Reads ``{session_id}_moments.json`` once and filters in memory; any
        ``key_moment_ids`` not present in the session bundle (different session
        or solo ``create_key_moment``) fall back to per-moment ``{id}.json``
        lookups via ``get_key_moment``. Missing moments are skipped silently,
        matching the previous per-id loop behavior.
        """
        needed_ids = list(record.experience.key_moment_ids)
        if not needed_ids:
            return []

        moments_by_id: dict[UUID, KeyMoment] = {}
        session_id = getattr(record.experience, "session_id", None)
        if session_id is not None:
            for moment in self.get_key_moments_for_session(session_id):
                moments_by_id[moment.id] = moment

        result: list[KeyMoment] = []
        for moment_id in needed_ids:
            moment = moments_by_id.get(moment_id)
            if moment is None:
                moment = self.get_key_moment(moment_id)
            if moment is not None:
                result.append(moment)
        return result

    def list_recent_experiences(self, limit: int = 10) -> list[ExperienceRecord]:
        """List recent experiences."""
        return self.search_experiences(query=None, limit=limit)

    def store_key_moments(self, session_id: UUID, moments: list[KeyMoment]) -> None:
        """Store key moments for a session."""
        session_moments_file = self.key_moments_dir / f"{session_id}_moments.json"
        moments_data = [m.model_dump(mode="json") for m in moments]
        self._write_json_atomically(session_moments_file, json.dumps(moments_data, indent=2))

        # Also store individual moment files for quick lookup
        for moment in moments:
            moment_file = self.key_moments_dir / f"{moment.id}.json"
            self._write_json_atomically(moment_file, moment.model_dump_json(indent=2))

    def get_key_moment(self, moment_id: UUID) -> KeyMoment | None:
        """Retrieve a key moment by ID.

        Fast path: per-moment ``{id}.json`` file written by all current write
        paths (``store_key_moments``, ``store_key_moment``, ``create_key_moment``).
        Falls back to a one-shot scan of ``key_moments.jsonl`` for moments
        written by **old** code that only appended to the JSONL log without
        materialising the per-moment file (e.g. legacy crash-recovery paths
        pre-HLE-43). If the JSONL hit matches, the per-moment file is
        backfilled so the next call hits the fast path.
        """
        moment_file = self.key_moments_dir / f"{moment_id}.json"
        if moment_file.exists():
            return KeyMoment.model_validate(_read_json_file(moment_file))

        if not self.key_moments_path.exists():
            return None
        target = str(moment_id)
        for line in self.key_moments_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if data.get("id") == target:
                moment = KeyMoment.model_validate(data)
                # Backfill the per-moment index file so future reads are O(1).
                self._write_json_atomically(moment_file, moment.model_dump_json(indent=2))
                return moment
        return None

    def get_key_moments_for_session(self, session_id: UUID) -> list[KeyMoment]:
        """Retrieve all key moments for a session."""
        session_moments_file = self.key_moments_dir / f"{session_id}_moments.json"
        if not session_moments_file.exists():
            return []
        data = _read_json_file(session_moments_file)
        return [KeyMoment.model_validate(m) for m in data]

    # Identity Store operations

    def load_identity(self, agent_id: UUID) -> Identity | None:
        """Load current identity."""
        if not self.identity_path.exists():
            return None

        data = _read_json_file(self.identity_path)
        identity = Identity.model_validate(data)

        # Check if this identity matches the requested agent_id
        if identity.id != agent_id:
            return None

        return identity

    def save_identity(self, identity: Identity, expected_version: str | None = None) -> Identity:
        """Save identity."""
        # Simple version check
        if expected_version is not None:
            existing = self.load_identity(identity.id)
            if existing is not None and existing.schema_version != expected_version:
                raise ValueError(
                    f"Version mismatch: expected {expected_version}, got {existing.schema_version}"
                )

        self._write_json_atomically(self.identity_path, identity.model_dump_json(indent=2))
        return identity

    def create_identity_snapshot(self, snapshot: IdentitySnapshot) -> IdentitySnapshot:
        """Create identity snapshot."""
        snapshot_file = self.identity_snapshots_dir / f"{snapshot.id}.json"
        self._write_json_atomically(snapshot_file, snapshot.model_dump_json(indent=2))
        return snapshot

    def list_identity_snapshots(self, identity_id: UUID, limit: int = 10) -> list[IdentitySnapshot]:
        """List identity snapshots."""
        snapshots: list[IdentitySnapshot] = []

        for snapshot_file in self.identity_snapshots_dir.glob("*.json"):
            data = _read_json_file(snapshot_file)
            snapshot = IdentitySnapshot.model_validate(data)

            if snapshot.identity_id == identity_id:
                snapshots.append(snapshot)

        # Sort by timestamp descending
        snapshots.sort(key=lambda s: s.timestamp, reverse=True)
        return snapshots[:limit]

    # Narrative Store operations

    def load_narrative(self, identity_id: UUID) -> NarrativeDocument | None:
        """Load current narrative."""
        if not self.narrative_path.exists():
            return None

        data = _read_json_file(self.narrative_path)
        narrative = NarrativeDocument.model_validate(data)

        # Check if this narrative matches the requested identity
        if narrative.identity_id != identity_id:
            return None

        return narrative

    def save_narrative(
        self,
        narrative: NarrativeDocument,
        expected_version: str | None = None,
        expected_updated_at: datetime | None = None,
    ) -> NarrativeDocument:
        """Save narrative."""
        existing = self.load_narrative(narrative.identity_id)
        # Simple version check
        if (
            expected_version is not None
            and existing is not None
            and existing.schema_version != expected_version
        ):
            raise ValueError(
                f"Version mismatch: expected {expected_version}, got {existing.schema_version}"
            )

        if expected_updated_at is not None:
            if existing is None:
                raise ValueError("Narrative missing on disk; cannot verify expected_updated_at")
            eu = existing.updated_at
            exp = expected_updated_at
            if eu.tzinfo is None:
                eu = eu.replace(tzinfo=UTC)
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=UTC)
            if eu != exp:
                raise ValueError(
                    "Narrative updated_at mismatch (concurrent update?). "
                    f"expected {expected_updated_at}, got {existing.updated_at}"
                )

        self._write_json_atomically(self.narrative_path, narrative.model_dump_json(indent=2))
        return narrative

    def archive_narrative(self, narrative_id: UUID, reason: str) -> None:
        """Archive narrative."""
        narrative = self._load_narrative_by_id(narrative_id)
        if narrative is None:
            return

        now = datetime.now(UTC)
        archive_entry = {
            "narrative": narrative.model_dump(mode="json"),
            "reason": reason,
            "archived_at": now.isoformat(),
        }

        # Save to archive
        archive_file = self.narrative_archive_dir / f"{narrative_id}_{now.timestamp()}.json"
        self._write_json_atomically(archive_file, json.dumps(archive_entry, indent=2))

    def list_archived_narratives(
        self, identity_id: UUID, limit: int = 10
    ) -> list[tuple[NarrativeDocument, str, datetime]]:
        """List archived narratives."""
        archived: list[tuple[NarrativeDocument, str, datetime]] = []

        for archive_file in self.narrative_archive_dir.glob("*.json"):
            data = _read_json_file(archive_file)

            narrative = NarrativeDocument.model_validate(data["narrative"])
            if narrative.identity_id == identity_id:
                reason = data["reason"]
                archived_at = datetime.fromisoformat(data["archived_at"])
                if archived_at.tzinfo is None:
                    archived_at = archived_at.replace(tzinfo=UTC)
                archived.append((narrative, reason, archived_at))

        # Sort by archived_at descending
        archived.sort(key=lambda x: x[2], reverse=True)
        return archived[:limit]

    # Eigenstate operations

    def save_eigenstate(self, eigenstate: Eigenstate) -> Eigenstate:
        """Save eigenstate."""
        self._write_json_atomically(self.eigenstate_path, eigenstate.model_dump_json(indent=2))
        return eigenstate

    def load_latest_eigenstate(
        self,
        session_id: UUID | None = None,
        identity_id: UUID | None = None,
    ) -> Eigenstate | None:
        """Load latest eigenstate."""
        if not self.eigenstate_path.exists():
            return None

        data = _read_json_file(self.eigenstate_path)
        eigenstate = Eigenstate.model_validate(data)

        if session_id is not None and eigenstate.session_id != session_id:
            return None

        if identity_id is not None:
            if eigenstate.identity_id is None:
                return None
            if eigenstate.identity_id != identity_id:
                return None

        return eigenstate

    def _load_narrative_by_id(self, narrative_id: UUID) -> NarrativeDocument | None:
        """Helper to load narrative by ID."""
        if not self.narrative_path.exists():
            return None

        data = _read_json_file(self.narrative_path)
        narrative = NarrativeDocument.model_validate(data)

        if narrative.id != narrative_id:
            return None

        return narrative

    # KeyMoment operations

    def create_key_moment(self, key_moment: KeyMoment) -> KeyMoment:
        """Create key moment — writes per-moment file and appends to JSONL log."""
        # Per-moment file is the source of truth for ``get_key_moment``;
        # treat its presence as the existence check (cheap O(1) stat vs
        # scanning the whole JSONL).
        moment_file = self.key_moments_dir / f"{key_moment.id}.json"
        if moment_file.exists():
            raise ValueError(f"KeyMoment {key_moment.id} already exists")

        self._write_json_atomically(moment_file, key_moment.model_dump_json(indent=2))

        # Append to JSONL log (kept for backwards compatibility with
        # ``list_key_moments`` and ``store_key_moment`` upsert path).
        with self.key_moments_path.open("a", encoding="utf-8") as f:
            f.write(key_moment.model_dump_json() + "\n")

        return key_moment

    def store_key_moment(self, moment: KeyMoment) -> KeyMoment:
        """Idempotent upsert — replaces existing record by id, or appends if new (v2 API).

        Updates all three storage layers used by FileStateStore so subsequent
        reads see the new state (no stale data from decay/access updates):
          1. key_moments.jsonl          — JSONL log of all moments
          2. {key_moments_dir}/{id}.json — per-moment file (checked first by get_key_moment)
          3. {key_moments_dir}/{session_id}_moments.json — per-session file
             (read by get_key_moments_for_session) — only updated if it exists
        """
        target_id = str(moment.id)
        existed = False
        rebuilt_lines: list[str] = []

        if self.key_moments_path.exists():
            for line in self.key_moments_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    rebuilt_lines.append(line)
                    continue
                if data.get("id") == target_id:
                    existed = True
                    rebuilt_lines.append(moment.model_dump_json())
                else:
                    rebuilt_lines.append(line)

        if existed:
            # Atomic rewrite: tmpfile + rename, so a crash mid-write cannot
            # truncate or corrupt the JSONL file (decay_pass calls this in a
            # loop over every moment, making partial-write risk significant).
            self._write_json_atomically(self.key_moments_path, "\n".join(rebuilt_lines) + "\n")
        else:
            with self.key_moments_path.open("a", encoding="utf-8") as f:
                f.write(moment.model_dump_json() + "\n")

        # Per-moment file: get_key_moment reads this first, so it MUST reflect
        # the latest state, not the stale snapshot from store_key_moments().
        moment_file = self.key_moments_dir / f"{moment.id}.json"
        self._write_json_atomically(moment_file, moment.model_dump_json(indent=2))

        # Per-session file: get_key_moments_for_session reads only from here.
        # Update in place (replace by id) if the file exists; do not create
        # the session file on first solo store_key_moment — the per-session
        # collection is owned by store_key_moments (plural).
        if moment.session_id is not None:
            session_file = self.key_moments_dir / f"{moment.session_id}_moments.json"
            if session_file.exists():
                try:
                    existing = _read_json_file(session_file)
                except (json.JSONDecodeError, ValueError):
                    existing = []
                if isinstance(existing, list):
                    replaced = False
                    for i, entry in enumerate(existing):
                        if isinstance(entry, dict) and entry.get("id") == target_id:
                            existing[i] = moment.model_dump(mode="json")
                            replaced = True
                            break
                    if not replaced:
                        existing.append(moment.model_dump(mode="json"))
                    self._write_json_atomically(session_file, json.dumps(existing, indent=2))

        return moment

    def list_key_moments(self, session_id: UUID | None = None) -> list[KeyMoment]:
        """List key moments from JSONL file, optionally filtered by session_id."""
        import warnings

        # session_id filtering is now supported via KeyMoment.session_id field

        if not self.key_moments_path.exists():
            return []

        key_moments: list[KeyMoment] = []
        for line in self.key_moments_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    data = json.loads(line)
                    key_moment = KeyMoment.model_validate(data)
                    key_moments.append(key_moment)
                except (json.JSONDecodeError, ValueError) as e:
                    import warnings

                    warnings.warn(
                        f"Skipping corrupted line in {self.key_moments_path}: {e}",
                        stacklevel=2,
                    )
                    continue

        if session_id is not None:
            key_moments = [km for km in key_moments if km.session_id == session_id]

        return key_moments

    # ----- Session operations (v2 — needed by ExperienceViewRepository) ------

    def _session_path(self, session_id: UUID) -> Path:
        return self.sessions_dir / f"{session_id}.json"

    def create_session(self, session: Session) -> Session:
        """Persist a new session record as {sessions_dir}/{id}.json."""
        path = self._session_path(session.id)
        self._write_json_atomically(path, session.model_dump_json(indent=2))
        return session

    def get_session(self, session_id: UUID) -> Session | None:
        """Retrieve session by ID, or None if not stored."""
        path = self._session_path(session_id)
        if not path.exists():
            return None
        data = _read_json_file(path)
        return Session.model_validate(data)

    def update_session(self, session: Session) -> Session:
        """Update session metadata via atomic write (replace-by-id)."""
        path = self._session_path(session.id)
        self._write_json_atomically(path, session.model_dump_json(indent=2))
        return session

    def _iter_sessions_for_agent(self, agent_id: UUID) -> list[Session]:
        sessions: list[Session] = []
        for session_file in self.sessions_dir.glob("*.json"):
            try:
                data = _read_json_file(session_file)
                s = Session.model_validate(data)
            except (json.JSONDecodeError, ValueError):
                import warnings

                warnings.warn(
                    f"Skipping corrupted session file {session_file}",
                    stacklevel=2,
                )
                continue
            if s.agent_id == agent_id:
                sessions.append(s)
        sessions.sort(key=lambda s: s.started_at, reverse=True)
        return sessions

    def list_recent_sessions(self, agent_id: UUID, *, limit: int = 10) -> list[Session]:
        """List most recent sessions for an agent, newest first."""
        return self._iter_sessions_for_agent(agent_id)[:limit]

    def list_sessions_in_range(
        self,
        agent_id: UUID,
        start: datetime,
        end: datetime,
    ) -> list[Session]:
        """HLE-59: native ranged scan over on-disk session journals.

        Reads every session JSON once and filters in Python — this is the
        same I/O profile as ``list_recent_sessions`` with no artificial
        ``limit`` cap, so historical reflections over agents with very
        large session counts no longer drop the oldest rows. Legacy session
        JSONs persisted without a timezone suffix yield naive
        ``started_at`` values via :meth:`Session.model_validate`; normalise
        via :func:`ensure_utc` so the inclusive range check doesn't raise
        ``TypeError`` against UTC-aware bounds.
        """
        from atman.core.clock_impl import ensure_utc

        return [
            s
            for s in self._iter_sessions_for_agent(agent_id)
            if start <= ensure_utc(s.started_at) <= end
        ]
