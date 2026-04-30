"""
Общие тесты для всех реализаций FactualMemory.
"""

import pytest

from atman.adapters.memory import InMemoryBackend, FileBackend
from atman.core.models import FactRecord
from pathlib import Path
from tempfile import NamedTemporaryFile


@pytest.fixture(params=['in_memory', 'file'])
def backend(request):
    """Параметризованная фикстура для тестирования всех backend'ов."""
    if request.param == 'in_memory':
        yield InMemoryBackend()
    else:
        with NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            filepath = Path(f.name)
        
        backend = FileBackend(filepath)
        
        yield backend
        
        if filepath.exists():
            filepath.unlink()


def test_basic_crud(backend):
    """Базовый CRUD тест для всех backend'ов."""
    fact = FactRecord(content="CRUD тест", source="test")
    added = backend.add_fact(fact)
    
    assert added.id == fact.id
    
    retrieved = backend.get_fact(fact.id)
    assert retrieved is not None
    assert retrieved.content == fact.content


def test_search_functionality(backend):
    """Тест поиска для всех backend'ов."""
    backend.add_fact(FactRecord(
        content="Важная задача",
        source="test",
        tags=["task", "important"]
    ))
    backend.add_fact(FactRecord(
        content="Обычное сообщение",
        source="test",
        tags=["info"]
    ))
    
    results = backend.search(query="задача")
    assert len(results) == 1
    
    results = backend.search(tags=["task"])
    assert len(results) == 1
    
    results = backend.search(query="важ", tags=["task"])
    assert len(results) == 1


def test_relations(backend):
    """Тест связей для всех backend'ов."""
    fact1 = backend.add_fact(FactRecord(content="Факт 1", source="test"))
    fact2 = backend.add_fact(FactRecord(content="Факт 2", source="test"))
    
    success = backend.link(fact1.id, fact2.id, "related")
    assert success
    
    retrieved = backend.get_fact(fact1.id)
    assert len(retrieved.relations) == 1
    assert retrieved.relations[0].target_id == fact2.id


def test_recent_facts(backend):
    """Тест получения последних фактов для всех backend'ов."""
    facts = []
    for i in range(5):
        fact = backend.add_fact(FactRecord(content=f"Факт {i}", source="test"))
        facts.append(fact)
    
    recent = backend.list_recent(limit=3)
    assert len(recent) == 3
    assert recent[0].id == facts[4].id
