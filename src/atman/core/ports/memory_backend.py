"""
Порт FactualMemory - интерфейс для работы с фактами.

Определяет контракт для всех реализаций factual memory storage.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from atman.core.models import FactRecord
from atman.core.models.fact import FactStatus


def validate_decay_factor(decay_factor: float) -> None:
    """Validate ``decay_factor`` lies in the closed interval ``[0.0, 1.0]``.

    Adapters call this at the entry of ``decay_stale_facts`` so an
    out-of-range value surfaces as a clear ``ValueError`` instead of
    propagating into a Pydantic ``salience <= 1.0`` validation failure
    deep in the model layer.
    """
    if not 0.0 <= decay_factor <= 1.0:
        raise ValueError(
            f"decay_factor must satisfy 0.0 <= decay_factor <= 1.0, got {decay_factor!r}"
        )


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
            status: New non-ACTIVE status (defaults to INVALIDATED). Passing
                FactStatus.ACTIVE is rejected with ValueError because
                invalidation must move a fact out of the ACTIVE lifecycle.
            note: Reason for invalidation
            superseded_by: ID of fact that replaces this one

        Returns:
            FactRecord | None: Updated fact or None if not found

        Raises:
            ValueError: If status is FactStatus.ACTIVE
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

        Only ACTIVE facts can be confirmed. Confirmation is a signal that
        the fact is still observed in fresh evidence — a non-ACTIVE fact
        (DISPUTED, SUPERSEDED, INVALIDATED) has already exited the active
        lifecycle and resurrecting it via a confirmation bump would be
        semantically wrong (e.g. an INVALIDATED fact's salience must stay
        at 0.0 unless it is explicitly re-activated through a separate API).

        Args:
            fact_id: ID of the fact to confirm

        Returns:
            bool: True if the fact was found AND ACTIVE and got confirmed.
                False if the fact was not found or is not ACTIVE.
        """
        pass

    @abstractmethod
    def decay_stale_facts(self, before: datetime, decay_factor: float = 0.5) -> int:
        """
        Decay salience of stale facts not confirmed since before the given time.

        Args:
            before: Cutoff time - facts not confirmed since this time are decayed
            decay_factor: Factor to multiply salience by; MUST satisfy
                ``0.0 <= decay_factor <= 1.0``. Out-of-range values raise
                ``ValueError`` so a confused caller does not trip the
                ``salience <= 1.0`` Pydantic field validator with a less
                descriptive error.

        Returns:
            int: Number of facts decayed

        Raises:
            ValueError: If ``decay_factor`` is outside ``[0.0, 1.0]``.
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
