"""
JSONL (JSON Lines) adapter for experience storage.

Stores each experience as one JSON line in a file.
Thread-safe for concurrent reads, uses file locking for writes.
"""

import json
import warnings
from pathlib import Path
from uuid import UUID

from atman.core.models import ExperienceRecord, KeyMoment, ReframingNote
from atman.core.ports import (
    DateRangeQuery,
    DepthQuery,
    ExperienceQuery,
    FactRefsContainsQuery,
    SessionExperienceQuery,
    StateStore,
    ValuesTouchedQuery,
)


class JsonlExperienceStore(StateStore):
    """
    JSONL-based implementation of StateStore.

    Each experience is stored as one JSON line in a file.
    Simple, human-readable, and suitable for local development.
    """

    def __init__(self, storage_path: str | Path = ".atman/experiences.jsonl"):
        """
        Initialize JSONL experience store.

        Args:
            storage_path: Path to the JSONL file
        """
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        if not self.storage_path.exists():
            self.storage_path.touch()

        # Key moments storage (separate JSONL file)
        self.key_moments_path = self.storage_path.parent / "key_moments.jsonl"
        if not self.key_moments_path.exists():
            self.key_moments_path.touch()

    def _read_all_experiences(self) -> dict[UUID, ExperienceRecord]:
        """
        Read all experiences from the file into memory.

        Returns:
            dict[UUID, ExperienceRecord]: Map of experience ID to record
        """
        experiences: dict[UUID, ExperienceRecord] = {}

        if not self.storage_path.exists():
            return experiences

        with open(self.storage_path, encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                    record = ExperienceRecord.model_validate(data)
                    experiences[record.experience.id] = record
                except Exception as e:
                    warnings.warn(
                        f"Failed to parse line {line_num}: {e}",
                        UserWarning,
                        stacklevel=1,
                    )
                    continue

        return experiences

    def _read_all_key_moments(self) -> dict[UUID, KeyMoment]:
        """
        Read all key moments from the file into memory.

        Returns:
            dict[UUID, KeyMoment]: Map of moment ID to KeyMoment
        """
        moments: dict[UUID, KeyMoment] = {}

        if not self.key_moments_path.exists():
            return moments

        with open(self.key_moments_path, encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                    moment = KeyMoment.model_validate(data)
                    moments[moment.id] = moment
                except Exception as e:
                    warnings.warn(
                        f"Failed to parse key moment line {line_num}: {e}",
                        UserWarning,
                        stacklevel=1,
                    )
                    continue

        return moments

    def _write_all_key_moments(self, moments: dict[UUID, KeyMoment]) -> None:
        """
        Write all key moments to the file.

        Args:
            moments: Map of moment ID to KeyMoment
        """
        with open(self.key_moments_path, "w", encoding="utf-8") as f:
            for moment in moments.values():
                json_str = moment.model_dump_json()
                f.write(json_str + "\n")

    def _write_all_experiences(self, experiences: dict[UUID, ExperienceRecord]) -> None:
        """
        Write all experiences to the file.

        Args:
            experiences: Map of experience ID to record
        """
        with open(self.storage_path, "w", encoding="utf-8") as f:
            for record in experiences.values():
                json_str = record.model_dump_json()
                f.write(json_str + "\n")

    def create_experience(self, record: ExperienceRecord) -> ExperienceRecord:
        """Create a new experience in storage."""
        experiences = self._read_all_experiences()

        if record.experience.id in experiences:
            raise ValueError(f"Experience with id {record.experience.id} already exists")

        experiences[record.experience.id] = record
        self._write_all_experiences(experiences)

        return record

    def get_experience(self, experience_id: UUID) -> ExperienceRecord | None:
        """Retrieve an experience by its ID."""
        experiences = self._read_all_experiences()
        return experiences.get(experience_id)

    def add_reframing_note(
        self, experience_id: UUID, note: ReframingNote
    ) -> ExperienceRecord | None:
        """Add a reframing note to an existing experience."""
        experiences = self._read_all_experiences()

        if experience_id not in experiences:
            return None

        record = experiences[experience_id]
        if note.triggered_by and any(
            n.triggered_by == note.triggered_by for n in record.experience.reframing_notes
        ):
            return record

        record.experience.reframing_notes.append(note)

        self._write_all_experiences(experiences)

        return record

    def mark_accessed(self, experience_id: UUID) -> ExperienceRecord | None:
        """Mark an experience as accessed."""
        from datetime import UTC, datetime

        experiences = self._read_all_experiences()

        if experience_id not in experiences:
            return None

        record = experiences[experience_id]
        record.experience.last_accessed_at = datetime.now(UTC)
        record.experience.access_count += 1

        self._write_all_experiences(experiences)

        return record

    def search_experiences(
        self, query: ExperienceQuery | None = None, limit: int = 10
    ) -> list[ExperienceRecord]:
        """Search for experiences matching a query."""
        experiences = self._read_all_experiences()
        results: list[ExperienceRecord] = []

        for record in experiences.values():
            if self._matches_query(record, query):
                results.append(record)

        # Sort by timestamp, newest first
        results.sort(key=lambda r: r.experience.timestamp, reverse=True)

        return results[:limit]

    def _matches_query(self, record: ExperienceRecord, query: ExperienceQuery | None) -> bool:
        """
        Check if a record matches the given query.

        Args:
            record: The experience record to check
            query: The query to match against

        Returns:
            bool: True if the record matches the query
        """
        if query is None:
            return True

        exp = record.experience

        if isinstance(query, SessionExperienceQuery):
            return exp.session_id == query.session_id

        elif isinstance(query, ValuesTouchedQuery):
            # Check if any of the query values are in any key moment's values_touched
            moments = self._read_all_key_moments()
            for moment_id in exp.key_moment_ids:
                moment = moments.get(moment_id)
                if moment and any(qv in moment.values_touched for qv in query.values):
                    return True
            return False

        elif isinstance(query, DepthQuery):
            # Check if any key moment has the specified depth
            moments = self._read_all_key_moments()
            for moment_id in exp.key_moment_ids:
                moment = moments.get(moment_id)
                if moment and moment.how_i_felt.depth.value == query.depth:
                    return True
            return False

        elif isinstance(query, DateRangeQuery):
            return query.start_date <= exp.timestamp <= query.end_date

        elif isinstance(query, FactRefsContainsQuery):
            # Check if any key moment contains the fact_id
            moments = self._read_all_key_moments()
            for moment_id in exp.key_moment_ids:
                moment = moments.get(moment_id)
                if moment and query.fact_id in moment.fact_refs:
                    return True
            return False

        return False

    def list_recent_experiences(self, limit: int = 10) -> list[ExperienceRecord]:
        """List the most recent experiences."""
        experiences = self._read_all_experiences()

        results = list(experiences.values())
        results.sort(key=lambda r: r.experience.timestamp, reverse=True)

        return results[:limit]

    def store_key_moments(self, session_id: UUID, moments: list[KeyMoment]) -> None:
        """Store key moments for a session."""
        all_moments = self._read_all_key_moments()
        for moment in moments:
            all_moments[moment.id] = moment
        self._write_all_key_moments(all_moments)

    def get_key_moment(self, moment_id: UUID) -> KeyMoment | None:
        """Retrieve a key moment by its ID."""
        moments = self._read_all_key_moments()
        return moments.get(moment_id)

    def get_key_moments_for_session(self, session_id: UUID) -> list[KeyMoment]:
        """Retrieve all key moments for a session."""
        # We need to scan experiences to find which moments belong to this session
        experiences = self._read_all_experiences()
        moments_dict = self._read_all_key_moments()

        session_exp = None
        for exp_record in experiences.values():
            if exp_record.experience.session_id == session_id:
                session_exp = exp_record.experience
                break

        if not session_exp:
            return []

        result = []
        for moment_id in session_exp.key_moment_ids:
            moment = moments_dict.get(moment_id)
            if moment:
                result.append(moment)

        return result

    # Identity Store operations (not implemented - for compatibility)

    def load_identity(self, agent_id):  # type: ignore
        """Not implemented - use FileStateStore for identity operations."""
        raise NotImplementedError("Identity operations not supported in JsonlExperienceStore")

    def save_identity(self, identity, expected_version=None):  # type: ignore
        """Not implemented - use FileStateStore for identity operations."""
        raise NotImplementedError("Identity operations not supported in JsonlExperienceStore")

    def create_identity_snapshot(self, snapshot):  # type: ignore
        """Not implemented - use FileStateStore for identity operations."""
        raise NotImplementedError("Identity operations not supported in JsonlExperienceStore")

    def list_identity_snapshots(self, identity_id, limit=10):  # type: ignore
        """Not implemented - use FileStateStore for identity operations."""
        raise NotImplementedError("Identity operations not supported in JsonlExperienceStore")

    def load_narrative(self, identity_id):  # type: ignore
        """Not implemented - use FileStateStore for narrative operations."""
        raise NotImplementedError("Narrative operations not supported in JsonlExperienceStore")

    def save_narrative(self, narrative, expected_version=None, expected_updated_at=None):  # type: ignore
        """Not implemented - use FileStateStore for narrative operations."""
        raise NotImplementedError("Narrative operations not supported in JsonlExperienceStore")

    def archive_narrative(self, narrative_id, reason):  # type: ignore
        """Not implemented - use FileStateStore for narrative operations."""
        raise NotImplementedError("Narrative operations not supported in JsonlExperienceStore")

    def list_archived_narratives(self, identity_id, limit=10):  # type: ignore
        """Not implemented - use FileStateStore for narrative operations."""
        raise NotImplementedError("Narrative operations not supported in JsonlExperienceStore")

    def save_eigenstate(self, eigenstate):  # type: ignore
        """Not implemented - use FileStateStore for eigenstate operations."""
        raise NotImplementedError("Eigenstate operations not supported in JsonlExperienceStore")

    def load_latest_eigenstate(self, session_id=None, identity_id=None):  # type: ignore
        """Not implemented - use FileStateStore for eigenstate operations."""
        raise NotImplementedError("Eigenstate operations not supported in JsonlExperienceStore")

    # KeyMoment operations (not implemented - for compatibility)

    def create_key_moment(self, key_moment):  # type: ignore
        """Not implemented - use FileStateStore for key moment operations."""
        raise NotImplementedError("KeyMoment operations not supported in JsonlExperienceStore")

    def list_key_moments(self, session_id=None):  # type: ignore
        """Not implemented - use FileStateStore for key moment operations."""
        raise NotImplementedError("KeyMoment operations not supported in JsonlExperienceStore")
