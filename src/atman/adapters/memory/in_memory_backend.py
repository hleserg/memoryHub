"""
In-memory адаптер для Factual Memory.

Используется для unit-тестов и быстрого прототипирования.
Все данные хранятся в памяти и теряются при завершении процесса.
"""

from datetime import UTC, datetime
from uuid import UUID

from atman.core.models import FactRecord, Relation
from atman.core.models.fact import FactStatus
from atman.core.ports import FactualMemory


class InMemoryBackend(FactualMemory):
    """
    In-memory реализация FactualMemory.

    Хранит все факты в словаре. Не персистентна.
    Подходит для тестов и разработки.
    """

    def __init__(self) -> None:
        self._facts: dict[UUID, FactRecord] = {}

    def add_fact(self, record: FactRecord) -> FactRecord:
        """Добавляет факт в память."""
        fact_copy = record.model_copy(deep=True)
        self._facts[fact_copy.id] = fact_copy
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
        """
        Ищет факты по запросу и тегам.

        Поиск по query использует простое вхождение подстроки (case-insensitive).
        Поиск по tags требует совпадения всех указанных тегов.
        """
        results = []

        normalized_query = query.lower() if query else None
        normalized_tags = [t.lower() for t in tags] if tags else None

        for fact in self._facts.values():
            if not include_invalidated and fact.status != FactStatus.ACTIVE:
                continue

            if normalized_query and normalized_query not in fact.content.lower():
                continue

            if normalized_tags:
                fact_tags_lower = [t.lower() for t in fact.tags]
                if not all(tag in fact_tags_lower for tag in normalized_tags):
                    continue

            results.append(fact.model_copy(deep=True))

            if len(results) >= limit:
                break

        return results

    def invalidate_fact(
        self,
        fact_id: UUID,
        *,
        status: FactStatus | None = None,
        note: str = "",
        superseded_by: UUID | None = None,
    ) -> FactRecord | None:
        """Mark a fact as invalidated, superseded, or disputed."""
        if status == FactStatus.ACTIVE:
            raise ValueError("invalidate_fact rejects FactStatus.ACTIVE")
        fact = self._facts.get(fact_id)
        if fact is None:
            return None

        new_status = status or FactStatus.INVALIDATED
        fact.status = new_status
        fact.invalidation_note = note
        # Set the timestamp appropriate to the new lifecycle status: DISPUTED
        # populates ``disputed_at``; INVALIDATED / SUPERSEDED populate
        # ``invalidated_at``.
        now = datetime.now(UTC)
        if new_status == FactStatus.DISPUTED:
            fact.disputed_at = now
        else:
            fact.invalidated_at = now
        fact.superseded_by = superseded_by

        if superseded_by is not None:
            new_fact = self._facts.get(superseded_by)
            if new_fact is not None:
                fact.relations.append(
                    Relation(target_id=superseded_by, relation_type="superseded_by")
                )
                new_fact.relations.append(Relation(target_id=fact_id, relation_type="supersedes"))

        return fact.model_copy(deep=True)

    def list_invalidated(self, since: datetime | None = None) -> list[FactRecord]:
        """List invalidated facts."""
        results = [
            f
            for f in self._facts.values()
            if f.status != FactStatus.ACTIVE
            and (since is None or (f.invalidated_at is not None and f.invalidated_at >= since))
        ]
        results.sort(
            key=lambda f: f.invalidated_at if f.invalidated_at is not None else datetime.min,
            reverse=True,
        )
        return [f.model_copy(deep=True) for f in results]

    def confirm_fact(self, fact_id: UUID) -> bool:
        """Confirm a fact, increasing its confirmation count."""
        fact = self._facts.get(fact_id)
        if fact is None:
            return False
        fact.confirm()
        return True

    def decay_stale_facts(self, before: datetime, decay_factor: float = 0.5) -> int:
        """Decay salience of facts not confirmed since before the given time."""
        count = 0
        for fact in self._facts.values():
            if fact.status != FactStatus.ACTIVE:
                continue
            if fact.last_confirmed_at is None or fact.last_confirmed_at < before:
                fact.salience = max(0.0, fact.salience * decay_factor)
                count += 1
        return count

    def link(self, source_id: UUID, target_id: UUID, relation_type: str) -> bool:
        """Создает связь между фактами."""
        source_fact = self._facts.get(source_id)
        target_fact = self._facts.get(target_id)

        if not source_fact or not target_fact:
            return False

        relation = Relation(target_id=target_id, relation_type=relation_type.strip().lower())

        source_fact.relations.append(relation)
        return True

    def list_recent(self, limit: int = 10) -> list[FactRecord]:
        """Возвращает последние факты, отсортированные по created_at."""
        sorted_facts = sorted(self._facts.values(), key=lambda f: f.created_at, reverse=True)

        return [f.model_copy(deep=True) for f in sorted_facts[:limit]]

    def clear(self) -> None:
        """Очищает все факты из памяти. Полезно для тестов."""
        self._facts.clear()

    def count(self) -> int:
        """Возвращает количество фактов в памяти."""
        return len(self._facts)
