"""
JSONL (JSON Lines) adapter for experience storage.

Stores each experience as one JSON line in a file.
Thread-safe for concurrent reads, uses file locking for writes.
"""

import json
import warnings
from pathlib import Path
from uuid import UUID

from atman.core.models import ExperienceRecord, ReframingNote
from atman.core.ports import (
    DateRangeQuery,
    DepthQuery,
    ExperienceQuery,
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
        record.experience.add_reframing_note(note)

        self._write_all_experiences(experiences)

        return record

    def mark_accessed(self, experience_id: UUID) -> ExperienceRecord | None:
        """Mark an experience as accessed."""
        experiences = self._read_all_experiences()

        if experience_id not in experiences:
            return None

        record = experiences[experience_id]
        record.experience.mark_accessed()

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
            query_values_lower = [v.lower() for v in query.values]
            for moment in exp.key_moments:
                moment_values_lower = [v.lower() for v in moment.values_touched]
                if any(qv in moment_values_lower for qv in query_values_lower):
                    return True
            return False

        elif isinstance(query, DepthQuery):
            # Check if any key moment has the specified depth
            return any(
                moment.how_i_felt.depth.value == query.depth.lower() for moment in exp.key_moments
            )

        elif isinstance(query, DateRangeQuery):
            return query.start_date <= exp.timestamp <= query.end_date

        return False

    def list_recent_experiences(self, limit: int = 10) -> list[ExperienceRecord]:
        """List the most recent experiences."""
        experiences = self._read_all_experiences()

        results = list(experiences.values())
        results.sort(key=lambda r: r.experience.timestamp, reverse=True)

        return results[:limit]
