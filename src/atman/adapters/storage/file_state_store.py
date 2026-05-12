"""
File-based StateStore implementation.

Stores identity, narrative, and eigenstate in JSON files.
Suitable for local development and single-agent use cases.
"""

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from atman.core.models import (
    Eigenstate,
    ExperienceRecord,
    Identity,
    IdentitySnapshot,
    KeyMoment,
    NarrativeDocument,
    ReframingNote,
)
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

        # Paths for current state files
        self.identity_path = self.workspace / "identity.json"
        self.narrative_path = self.workspace / "narrative.json"
        self.eigenstate_path = self.workspace / "eigenstate.json"
        self.key_moments_path = self.workspace / "key_moments.jsonl"

    def _write_json_atomically(self, path: Path, content: str) -> None:
        """Write JSON without exposing callers to partially rewritten files."""
        path.parent.mkdir(parents=True, exist_ok=True)
        file_mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
        temp_file = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        )
        temp_path = Path(temp_file.name)

        try:
            with temp_file as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())

            temp_path.chmod(file_mode)
            os.replace(temp_path, path)
        finally:
            if temp_path.exists():
                temp_path.unlink()

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
        record.experience.add_reframing_note(note)
        experience_file = self.experiences_dir / f"{experience_id}.json"
        self._write_json_atomically(experience_file, record.model_dump_json(indent=2))
        return record

    def mark_accessed(self, experience_id: UUID) -> ExperienceRecord | None:
        """Mark experience as accessed."""
        record = self.get_experience(experience_id)
        if record is None:
            return None
        record.experience.mark_accessed()
        experience_file = self.experiences_dir / f"{experience_id}.json"
        self._write_json_atomically(experience_file, record.model_dump_json(indent=2))
        return record

    def search_experiences(
        self, query: ExperienceQuery | None = None, limit: int = 10
    ) -> list[ExperienceRecord]:
        """Search experiences (basic implementation)."""
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
            elif isinstance(query, ValuesTouchedQuery):
                for moment_id in record.experience.key_moment_ids:
                    moment = self.get_key_moment(moment_id)
                    if moment and any(v in moment.values_touched for v in query.values):
                        all_experiences.append(record)
                        break
            elif isinstance(query, DepthQuery):
                for moment_id in record.experience.key_moment_ids:
                    moment = self.get_key_moment(moment_id)
                    if moment and moment.how_i_felt.depth == query.depth:
                        all_experiences.append(record)
                        break
            elif (
                isinstance(query, DateRangeQuery)
                and query.start_date <= record.experience.timestamp <= query.end_date
            ):
                all_experiences.append(record)
            elif isinstance(query, FactRefsContainsQuery):
                # Check fact refs in key moments (fetch by ID)
                for moment_id in record.experience.key_moment_ids:
                    moment = self.get_key_moment(moment_id)
                    if moment and query.fact_id in moment.fact_refs:
                        all_experiences.append(record)
                        break

        # Sort by timestamp descending
        all_experiences.sort(key=lambda r: r.experience.timestamp, reverse=True)
        return all_experiences[:limit]

    def list_recent_experiences(self, limit: int = 10) -> list[ExperienceRecord]:
        """List recent experiences."""
        return self.search_experiences(query=None, limit=limit)

    def store_key_moments(self, session_id: UUID, moments: list[KeyMoment]) -> None:
        """Store key moments for a session."""
        session_moments_file = self.key_moments_dir / f"{session_id}_moments.json"
        moments_data = [m.model_dump(mode='json') for m in moments]
        self._write_json_atomically(session_moments_file, json.dumps(moments_data, indent=2))

        # Also store individual moment files for quick lookup
        for moment in moments:
            moment_file = self.key_moments_dir / f"{moment.id}.json"
            self._write_json_atomically(moment_file, moment.model_dump_json(indent=2))

    def get_key_moment(self, moment_id: UUID) -> KeyMoment | None:
        """Retrieve a key moment by its ID."""
        moment_file = self.key_moments_dir / f"{moment_id}.json"
        if not moment_file.exists():
            return None
        data = _read_json_file(moment_file)
        return KeyMoment.model_validate(data)

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
        """Create key moment by appending to JSONL file."""
        import warnings

        # Check if key moment already exists
        if self.key_moments_path.exists():
            for line in self.key_moments_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        data = json.loads(line)
                        if data.get("id") == str(key_moment.id):
                            raise ValueError(f"KeyMoment {key_moment.id} already exists")
                    except json.JSONDecodeError as e:
                        warnings.warn(
                            f"Skipping corrupted line in {self.key_moments_path}: {e}",
                            stacklevel=2,
                        )
                        continue

        # Append to JSONL file
        with self.key_moments_path.open("a", encoding="utf-8") as f:
            f.write(key_moment.model_dump_json() + "\n")

        return key_moment

    def list_key_moments(self, session_id: UUID | None = None) -> list[KeyMoment]:
        """List key moments from JSONL file, optionally filtered by session_id."""
        import warnings

        # KeyMoment model doesn't have session_id field yet; filtering not implemented
        if session_id is not None:
            raise NotImplementedError(
                "Filtering by session_id not yet supported - KeyMoment model needs session_id field"
            )

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
                    warnings.warn(
                        f"Skipping corrupted line in {self.key_moments_path}: {e}",
                        stacklevel=2,
                    )
                    continue

        return key_moments

    def get_key_moment(self, key_moment_id: UUID) -> KeyMoment:
        """Retrieve key moment by ID from JSONL file."""
        import warnings

        if not self.key_moments_path.exists():
            raise KeyError(f"KeyMoment {key_moment_id} not found")

        for line in self.key_moments_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    data = json.loads(line)
                    if data.get("id") == str(key_moment_id):
                        return KeyMoment.model_validate(data)
                except (json.JSONDecodeError, ValueError) as e:
                    warnings.warn(
                        f"Skipping corrupted line in {self.key_moments_path}: {e}",
                        stacklevel=2,
                    )
                    continue

        raise KeyError(f"KeyMoment {key_moment_id} not found")
