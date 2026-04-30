"""
Unit-тесты для FileBackend.
"""

import pytest
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

from atman.adapters.memory import FileBackend
from atman.core.models import FactRecord


@pytest.fixture
def temp_file():
    """Фикстура с временным файлом."""
    with NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
        filepath = Path(f.name)
    
    yield filepath
    
    if filepath.exists():
        filepath.unlink()


@pytest.fixture
def backend(temp_file):
    """Фикстура с file backend."""
    return FileBackend(temp_file)


def test_add_and_get_fact(backend):
    """Тест добавления и получения факта."""
    fact = FactRecord(content="Тестовый факт", source="test")
    added = backend.add_fact(fact)
    
    assert added.id == fact.id
    retrieved = backend.get_fact(fact.id)
    assert retrieved is not None
    assert retrieved.content == fact.content


def test_persistence(temp_file):
    """Тест персистентности данных."""
    backend1 = FileBackend(temp_file)
    fact = FactRecord(content="Персистентный факт", source="test")
    added = backend1.add_fact(fact)
    
    backend2 = FileBackend(temp_file)
    retrieved = backend2.get_fact(added.id)
    
    assert retrieved is not None
    assert retrieved.id == added.id
    assert retrieved.content == added.content


def test_search_by_query(backend):
    """Тест поиска по запросу."""
    backend.add_fact(FactRecord(content="Пользователь попросил", source="test"))
    backend.add_fact(FactRecord(content="Система ответила", source="test"))
    
    results = backend.search(query="пользователь")
    assert len(results) == 1


def test_search_by_tags(backend):
    """Тест поиска по тегам."""
    backend.add_fact(FactRecord(content="Факт 1", source="test", tags=["task"]))
    backend.add_fact(FactRecord(content="Факт 2", source="test", tags=["info"]))
    
    results = backend.search(tags=["task"])
    assert len(results) == 1


def test_link_facts(backend):
    """Тест создания связи."""
    fact1 = backend.add_fact(FactRecord(content="Причина", source="test"))
    fact2 = backend.add_fact(FactRecord(content="Следствие", source="test"))
    
    success = backend.link(fact1.id, fact2.id, "caused")
    assert success
    
    retrieved = backend.get_fact(fact1.id)
    assert len(retrieved.relations) == 1


def test_link_persistence(temp_file):
    """Тест персистентности связей."""
    backend1 = FileBackend(temp_file)
    fact1 = backend1.add_fact(FactRecord(content="Факт 1", source="test"))
    fact2 = backend1.add_fact(FactRecord(content="Факт 2", source="test"))
    backend1.link(fact1.id, fact2.id, "related")
    
    backend2 = FileBackend(temp_file)
    retrieved = backend2.get_fact(fact1.id)
    
    assert len(retrieved.relations) == 1
    assert retrieved.relations[0].target_id == fact2.id


def test_list_recent(backend):
    """Тест получения последних фактов."""
    for i in range(5):
        backend.add_fact(FactRecord(content=f"Факт {i}", source="test"))
    
    recent = backend.list_recent(limit=3)
    assert len(recent) == 3


def test_empty_file_creation(temp_file):
    """Тест создания нового файла при отсутствии."""
    temp_file.unlink()
    
    backend = FileBackend(temp_file)
    assert backend.count() == 0
    
    backend.add_fact(FactRecord(content="Первый факт", source="test"))
    assert temp_file.exists()


def test_count(backend):
    """Тест подсчета фактов."""
    assert backend.count() == 0
    
    backend.add_fact(FactRecord(content="Факт", source="test"))
    assert backend.count() == 1


def test_multiple_facts_persistence(temp_file):
    """Тест сохранения множества фактов."""
    backend = FileBackend(temp_file)
    
    facts = []
    for i in range(10):
        fact = backend.add_fact(
            FactRecord(
                content=f"Факт {i}",
                source="test",
                tags=[f"tag{i}"]
            )
        )
        facts.append(fact)
    
    backend2 = FileBackend(temp_file)
    assert backend2.count() == 10
    
    for original in facts:
        retrieved = backend2.get_fact(original.id)
        assert retrieved is not None
        assert retrieved.content == original.content
