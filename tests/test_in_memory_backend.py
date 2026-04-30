"""
Unit-тесты для InMemoryBackend.
"""

import pytest
from uuid import uuid4

from atman.adapters.memory import InMemoryBackend
from atman.core.models import FactRecord


@pytest.fixture
def backend():
    """Фикстура с in-memory backend."""
    return InMemoryBackend()


def test_add_and_get_fact(backend):
    """Тест добавления и получения факта."""
    fact = FactRecord(content="Тестовый факт", source="test")
    added = backend.add_fact(fact)
    
    assert added.id == fact.id
    assert added.content == fact.content
    
    retrieved = backend.get_fact(fact.id)
    assert retrieved is not None
    assert retrieved.id == fact.id
    assert retrieved.content == fact.content


def test_get_nonexistent_fact(backend):
    """Тест получения несуществующего факта."""
    result = backend.get_fact(uuid4())
    assert result is None


def test_search_by_query(backend):
    """Тест поиска по текстовому запросу."""
    backend.add_fact(FactRecord(content="Пользователь попросил X", source="test"))
    backend.add_fact(FactRecord(content="Система выполнила задачу", source="test"))
    backend.add_fact(FactRecord(content="Пользователь подтвердил результат", source="test"))
    
    results = backend.search(query="пользователь")
    assert len(results) == 2
    assert all("пользователь" in r.content.lower() for r in results)


def test_search_by_tags(backend):
    """Тест поиска по тегам."""
    backend.add_fact(FactRecord(content="Факт 1", source="test", tags=["task", "urgent"]))
    backend.add_fact(FactRecord(content="Факт 2", source="test", tags=["task"]))
    backend.add_fact(FactRecord(content="Факт 3", source="test", tags=["info"]))
    
    results = backend.search(tags=["task"])
    assert len(results) == 2
    
    results = backend.search(tags=["task", "urgent"])
    assert len(results) == 1


def test_search_by_query_and_tags(backend):
    """Тест поиска по запросу и тегам одновременно."""
    backend.add_fact(FactRecord(content="Важная задача", source="test", tags=["task"]))
    backend.add_fact(FactRecord(content="Важное сообщение", source="test", tags=["info"]))
    backend.add_fact(FactRecord(content="Задача завершена", source="test", tags=["task"]))
    
    results = backend.search(query="важ", tags=["task"])
    assert len(results) == 1
    assert results[0].content == "Важная задача"


def test_search_with_limit(backend):
    """Тест ограничения количества результатов."""
    for i in range(10):
        backend.add_fact(FactRecord(content=f"Факт {i}", source="test"))
    
    results = backend.search(limit=5)
    assert len(results) == 5


def test_link_facts(backend):
    """Тест создания связи между фактами."""
    fact1 = backend.add_fact(FactRecord(content="Причина", source="test"))
    fact2 = backend.add_fact(FactRecord(content="Следствие", source="test"))
    
    success = backend.link(fact1.id, fact2.id, "caused")
    assert success
    
    retrieved = backend.get_fact(fact1.id)
    assert len(retrieved.relations) == 1
    assert retrieved.relations[0].target_id == fact2.id
    assert retrieved.relations[0].relation_type == "caused"


def test_link_nonexistent_facts(backend):
    """Тест создания связи с несуществующими фактами."""
    fact1 = backend.add_fact(FactRecord(content="Факт", source="test"))
    
    success = backend.link(fact1.id, uuid4(), "related")
    assert not success
    
    success = backend.link(uuid4(), fact1.id, "related")
    assert not success


def test_list_recent(backend):
    """Тест получения последних фактов."""
    facts = []
    for i in range(5):
        fact = backend.add_fact(FactRecord(content=f"Факт {i}", source="test"))
        facts.append(fact)
    
    recent = backend.list_recent(limit=3)
    assert len(recent) == 3
    
    assert recent[0].id == facts[4].id
    assert recent[1].id == facts[3].id
    assert recent[2].id == facts[2].id


def test_empty_list_recent(backend):
    """Тест получения последних фактов из пустого хранилища."""
    recent = backend.list_recent()
    assert len(recent) == 0


def test_fact_immutability(backend):
    """Тест что backend не мутирует возвращаемые факты."""
    original = FactRecord(content="Оригинал", source="test", tags=["tag1"])
    added = backend.add_fact(original)
    
    added.content = "Изменено"
    added.tags.append("tag2")
    
    retrieved = backend.get_fact(original.id)
    assert retrieved.content == "Оригинал"
    assert retrieved.tags == ["tag1"]


def test_count(backend):
    """Тест подсчета фактов."""
    assert backend.count() == 0
    
    backend.add_fact(FactRecord(content="Факт 1", source="test"))
    assert backend.count() == 1
    
    backend.add_fact(FactRecord(content="Факт 2", source="test"))
    assert backend.count() == 2


def test_clear(backend):
    """Тест очистки хранилища."""
    backend.add_fact(FactRecord(content="Факт 1", source="test"))
    backend.add_fact(FactRecord(content="Факт 2", source="test"))
    
    backend.clear()
    assert backend.count() == 0
