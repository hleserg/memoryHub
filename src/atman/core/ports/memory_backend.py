"""
Порт FactualMemory - интерфейс для работы с фактами.

Определяет контракт для всех реализаций factual memory storage.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from atman.core.models import FactRecord
from atman.core.models.fact import FactStatus


class FactualMemory(ABC):
    """
    Интерфейс для работы с factual memory storage.

    Предоставляет операции для:
    - Добавления фактов
    - Получения фактов по ID
    - Поиска фактов по запросу и тегам
    - Создания связей между фактами
    - Получения списка последних фактов
    """

    @abstractmethod
    def add_fact(self, record: FactRecord) -> FactRecord:
        """
        Добавляет новый факт в хранилище.

        Args:
            record: Запись факта для добавления

        Returns:
            FactRecord: Добавленная запись с заполненным ID и created_at
        """
        pass

    @abstractmethod
    def get_fact(self, fact_id: UUID) -> FactRecord | None:
        """
        Получает факт по его ID.

        Args:
            fact_id: UUID факта

        Returns:
            FactRecord | None: Найденный факт или None
        """
        pass

    @abstractmethod
    def search(
        self,
        query: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
        *,
        include_invalidated: bool = False,
    ) -> list[FactRecord]:
        """
        Ищет факты по текстовому запросу и/или тегам.

        Args:
            query: Текстовый запрос для поиска в content
            tags: Список тегов для фильтрации
            limit: Максимальное количество результатов
            include_invalidated: Whether to include invalidated facts in results

        Returns:
            list[FactRecord]: Список найденных фактов
        """
        pass

    @abstractmethod
    def invalidate_fact(
        self,
        fact_id: UUID,
        *,
        status: FactStatus | None = None,
        note: str = "",
        superseded_by: UUID | None = None,
    ) -> FactRecord | None:
        """
        Mark a fact as invalidated with a reason.

        Args:
            fact_id: ID of the fact to invalidate
            status: New status (defaults to INVALIDATED)
            note: Reason for invalidation
            superseded_by: ID of fact that replaces this one

        Returns:
            FactRecord | None: Updated fact or None if not found
        """
        pass

    @abstractmethod
    def list_invalidated(self, since: datetime | None = None) -> list[FactRecord]:
        """
        List invalidated facts.

        Args:
            since: Only return facts invalidated since this time

        Returns:
            list[FactRecord]: List of invalidated facts
        """
        pass

    @abstractmethod
    def confirm_fact(self, fact_id: UUID) -> bool:
        """
        Confirm a fact, increasing its confirmation count and salience.

        Args:
            fact_id: ID of the fact to confirm

        Returns:
            bool: True if fact was found and confirmed
        """
        pass

    @abstractmethod
    def decay_stale_facts(self, before: datetime, decay_factor: float = 0.5) -> int:
        """
        Decay salience of stale facts not confirmed since before the given time.

        Args:
            before: Cutoff time - facts not confirmed since this time are decayed
            decay_factor: Factor to multiply salience by (0.0-1.0)

        Returns:
            int: Number of facts decayed
        """
        pass

    @abstractmethod
    def link(self, source_id: UUID, target_id: UUID, relation_type: str) -> bool:
        """
        Создает связь между двумя фактами.

        Args:
            source_id: ID исходного факта
            target_id: ID целевого факта
            relation_type: Тип связи

        Returns:
            bool: True если связь создана успешно
        """
        pass

    @abstractmethod
    def list_recent(self, limit: int = 10) -> list[FactRecord]:
        """
        Возвращает список последних добавленных фактов.

        Args:
            limit: Максимальное количество фактов

        Returns:
            list[FactRecord]: Список фактов, отсортированных по created_at (новые первыми)
        """
        pass

    # ------------------------------------------------------------------
    # Entity-link operations (v2 — see migration 0007 fact_entities table)
    # ------------------------------------------------------------------

    def add_fact_with_entities(
        self,
        record: FactRecord,
        entities: list[tuple[UUID, str]],
    ) -> FactRecord:
        """Add a fact and link it to a list of (entity_id, role) pairs.

        ``role`` must be one of ``subject | object | context | mentioned`` per
        the `agent_N.fact_entities` CHECK constraint. The default
        implementation calls :meth:`add_fact` and ignores the links — adapters
        backed by a relational store with a ``fact_entities`` table MUST
        override to actually persist the rows.
        """
        return self.add_fact(record)

    def find_facts_by_entity(
        self,
        entity_id: UUID,
        roles: list[str] | None = None,
        *,
        limit: int = 20,
    ) -> list[FactRecord]:
        """Return facts linked to ``entity_id`` (optionally filtered by role).

        Default returns ``[]`` for adapters without entity-link support;
        Postgres adapters with the ``fact_entities`` table override.
        """
        return []
