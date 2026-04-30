"""
In-memory адаптер для Factual Memory.

Используется для unit-тестов и быстрого прототипирования.
Все данные хранятся в памяти и теряются при завершении процесса.
"""

from copy import deepcopy
from uuid import UUID

from atman.core.models import FactRecord, Relation
from atman.core.ports import FactualMemory


class InMemoryBackend(FactualMemory):
    """
    In-memory реализация FactualMemory.
    
    Хранит все факты в словаре. Не персистентна.
    Подходит для тестов и разработки.
    """
    
    def __init__(self):
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
        limit: int = 10
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
            # Проверка совпадения по запросу
            if normalized_query and normalized_query not in fact.content.lower():
                continue
            
            # Проверка совпадения по тегам
            if normalized_tags:
                fact_tags_lower = [t.lower() for t in fact.tags]
                if not all(tag in fact_tags_lower for tag in normalized_tags):
                    continue
            
            results.append(fact.model_copy(deep=True))
            
            if len(results) >= limit:
                break
        
        return results
    
    def link(self, source_id: UUID, target_id: UUID, relation_type: str) -> bool:
        """Создает связь между фактами."""
        source_fact = self._facts.get(source_id)
        target_fact = self._facts.get(target_id)
        
        if not source_fact or not target_fact:
            return False
        
        relation = Relation(
            target_id=target_id,
            relation_type=relation_type.strip().lower()
        )
        
        source_fact.relations.append(relation)
        return True
    
    def list_recent(self, limit: int = 10) -> list[FactRecord]:
        """Возвращает последние факты, отсортированные по created_at."""
        sorted_facts = sorted(
            self._facts.values(),
            key=lambda f: f.created_at,
            reverse=True
        )
        
        return [f.model_copy(deep=True) for f in sorted_facts[:limit]]
    
    def clear(self):
        """Очищает все факты из памяти. Полезно для тестов."""
        self._facts.clear()
    
    def count(self) -> int:
        """Возвращает количество фактов в памяти."""
        return len(self._facts)
