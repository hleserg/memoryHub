"""
File-based адаптер для Factual Memory.

Использует JSONL (JSON Lines) формат для хранения фактов в файле.
Подходит для локального запуска без внешних зависимостей.
"""

import fcntl
import json
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from atman.adapters.storage._atomic_write import write_atomically
from atman.core.models import FactRecord, Relation
from atman.core.models.fact import FactStatus
from atman.core.ports import FactualMemory


class FileBackend(FactualMemory):
    """
    File-based реализация FactualMemory с использованием JSONL.

    Каждый факт сохраняется как отдельная JSON-строка в файле.
    При запуске все факты загружаются в память для быстрого доступа.
    """

    def __init__(self, filepath: str | Path) -> None:
        """
        Инициализирует file backend.

        Args:
            filepath: Путь к JSONL файлу для хранения фактов
        """
        self.filepath = Path(filepath)
        self._lockpath = self.filepath.with_name(f".{self.filepath.name}.lock")
        self._facts: dict[UUID, FactRecord] = {}
        self._load_facts()

    def _load_facts(self) -> None:
        """Загружает факты из файла в память."""
        self._facts = self._read_facts_from_disk()

    def _read_facts_from_disk(self) -> dict[UUID, FactRecord]:
        """Читает актуальные факты с диска без изменения состояния backend."""
        if not self.filepath.exists():
            self.filepath.parent.mkdir(parents=True, exist_ok=True)
            return {}

        facts: dict[UUID, FactRecord] = {}
        with open(self.filepath, encoding="utf-8") as f:
            for line_number, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    fact = FactRecord.model_validate(data)
                except (json.JSONDecodeError, ValueError) as exc:
                    warnings.warn(
                        f"Skipping malformed fact at {self.filepath}:{line_number}: "
                        f"{type(exc).__name__}: {exc}",
                        RuntimeWarning,
                        stacklevel=2,
                    )
                    continue
                facts[fact.id] = fact

        return facts

    @contextmanager
    def _storage_lock(self) -> Iterator[None]:
        """Сериализует операции read-modify-write между экземплярами FileBackend."""
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(self._lockpath, "a", encoding="utf-8") as lock_file:
            self._lockpath.chmod(0o600)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _save_facts(self, facts: dict[UUID, FactRecord] | None = None) -> None:
        """Сохраняет все факты в файл атомарной заменой."""
        facts_to_save = facts if facts is not None else self._facts
        content = "".join(fact.model_dump_json() + "\n" for fact in facts_to_save.values())
        write_atomically(self.filepath, content)

    def add_fact(self, record: FactRecord) -> FactRecord:
        """Добавляет факт и сохраняет в файл."""
        fact_copy = record.model_copy(deep=True)
        with self._storage_lock():
            updated_facts = self._read_facts_from_disk()
            if fact_copy.id in updated_facts:
                self._facts = updated_facts
                raise ValueError(
                    f"Duplicate fact id: a record with id {fact_copy.id} already exists"
                )
            updated_facts[fact_copy.id] = fact_copy
            self._save_facts(updated_facts)
            self._facts = updated_facts
        return fact_copy.model_copy(deep=True)

    def get_fact(self, fact_id: UUID) -> FactRecord | None:
        """Получает факт по ID."""
        fact = self._facts.get(fact_id)
        return fact.model_copy(deep=True) if fact else None

    def search(
        self,
        query: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
        *,
        include_invalidated: bool = False,
    ) -> list[FactRecord]:
        """Ищет факты по запросу и тегам.

        query — case-insensitive substring filter (для CLI/точного поиска).
        Для семантического RAG передавайте ``query=None`` и фильтруйте
        по embedding similarity на уровне сервиса.

        Результаты сортируются по убыванию salience.
        """
        normalized_query = query.lower() if query else None
        normalized_tags = [t.lower() for t in tags] if tags else None

        candidates: list[FactRecord] = []
        for fact in self._facts.values():
            if not include_invalidated and fact.status != FactStatus.ACTIVE:
                continue

            if normalized_query and normalized_query not in fact.content.lower():
                continue

            if normalized_tags:
                fact_tags_lower = [t.lower() for t in fact.tags]
                if not all(tag in fact_tags_lower for tag in normalized_tags):
                    continue

            candidates.append(fact.model_copy(deep=True))

        candidates.sort(key=lambda f: f.salience, reverse=True)
        return candidates[:limit]

    def confirm_fact(self, fact_id: UUID) -> bool:
        """Confirm a fact and persist changes."""
        with self._storage_lock():
            updated_facts = self._read_facts_from_disk()
            fact = updated_facts.get(fact_id)
            if fact is None:
                self._facts = updated_facts
                return False
            if fact.status != FactStatus.ACTIVE:
                self._facts = updated_facts
                return False
            fact.confirm()
            self._save_facts(updated_facts)
            self._facts = updated_facts
        return True

    def decay_stale_facts(self, before: datetime, decay_factor: float = 0.5) -> int:
        """Decay salience of stale facts and persist changes."""
        count = 0
        with self._storage_lock():
            updated_facts = self._read_facts_from_disk()
            for fact in updated_facts.values():
                # Skip invalidated facts
                if fact.status != FactStatus.ACTIVE:
                    continue
                # Decay if never confirmed or last confirmation was before cutoff
                if fact.last_confirmed_at is None or fact.last_confirmed_at < before:
                    fact.salience = max(0.0, fact.salience * decay_factor)
                    count += 1
            if count > 0:
                self._save_facts(updated_facts)
            self._facts = updated_facts
        return count

    def link(self, source_id: UUID, target_id: UUID, relation_type: str) -> bool:
        """Создает связь между фактами и сохраняет в файл."""
        with self._storage_lock():
            updated_facts = self._read_facts_from_disk()
            source_fact = updated_facts.get(source_id)
            target_fact = updated_facts.get(target_id)

            if not source_fact or not target_fact:
                self._facts = updated_facts
                return False

            relation = Relation(target_id=target_id, relation_type=relation_type.strip().lower())

            updated_source = source_fact.model_copy(deep=True)
            updated_source.relations.append(relation)
            updated_facts[source_id] = updated_source

            self._save_facts(updated_facts)
            self._facts = updated_facts
        return True

    def list_recent(self, limit: int = 10) -> list[FactRecord]:
        """Возвращает последние факты."""
        sorted_facts = sorted(self._facts.values(), key=lambda f: f.created_at, reverse=True)

        return [f.model_copy(deep=True) for f in sorted_facts[:limit]]

    def invalidate_fact(
        self,
        fact_id: UUID,
        *,
        status: FactStatus | None = None,
        note: str = "",
        superseded_by: UUID | None = None,
    ) -> FactRecord | None:
        """Invalidates a fact by setting its status and metadata."""
        with self._storage_lock():
            updated_facts = self._read_facts_from_disk()
            fact = updated_facts.get(fact_id)
            if fact is None:
                self._facts = updated_facts
                return None

            now = datetime.now(UTC)
            fact.status = status or FactStatus.INVALIDATED
            fact.invalidation_note = note
            fact.invalidated_at = now
            fact.superseded_by = superseded_by

            if superseded_by is not None:
                new_fact = updated_facts.get(superseded_by)
                if new_fact is not None:
                    fact.relations.append(
                        Relation(target_id=superseded_by, relation_type="superseded_by")
                    )
                    new_fact.relations.append(
                        Relation(target_id=fact_id, relation_type="supersedes")
                    )

            self._save_facts(updated_facts)
            self._facts = updated_facts

        return fact.model_copy(deep=True)

    def list_invalidated(self, since: datetime | None = None) -> list[FactRecord]:
        """Returns all invalidated (non-ACTIVE) facts."""
        results = [
            fact
            for fact in self._facts.values()
            if fact.status != FactStatus.ACTIVE
            and (
                since is None or (fact.invalidated_at is not None and fact.invalidated_at >= since)
            )
        ]
        results.sort(
            key=lambda f: f.invalidated_at if f.invalidated_at is not None else datetime.min,
            reverse=True,
        )
        return [f.model_copy(deep=True) for f in results]

    def count(self) -> int:
        """Возвращает количество фактов."""
        return len(self._facts)
