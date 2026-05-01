"""
Порт FactualMemory - интерфейс для работы с фактами.

Определяет контракт для всех реализаций factual memory storage.
"""

from abc import ABC, abstractmethod
from uuid import UUID

from atman.core.models import FactRecord


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
        self, query: str | None = None, tags: list[str] | None = None, limit: int = 10
    ) -> list[FactRecord]:
        """
        Ищет факты по текстовому запросу и/или тегам.

        Args:
            query: Текстовый запрос для поиска в content
            tags: Список тегов для фильтрации
            limit: Максимальное количество результатов

        Returns:
            list[FactRecord]: Список найденных фактов
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
