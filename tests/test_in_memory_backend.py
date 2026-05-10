"""
Unit-тесты для InMemoryBackend.
"""

from uuid import uuid4

import pytest

from atman.adapters.memory import InMemoryBackend
from atman.core.models import FactRecord, FactStatus


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


# --- E24.1: FactStatus, invalidation, search filtering ---


def test_search_excludes_invalidated_by_default(backend):
    """E24.1 AC-3: search() with no args returns only ACTIVE facts."""
    active = backend.add_fact(FactRecord(content="Active fact", source="test"))
    superseded = backend.add_fact(FactRecord(content="Superseded fact", source="test"))
    backend.invalidate_fact(superseded.id, status=FactStatus.SUPERSEDED, note="old")

    results = backend.search()
    assert len(results) == 1
    assert results[0].id == active.id


def test_search_includes_invalidated_when_requested(backend):
    """E24.1 AC-4: search(include_invalidated=True) returns all facts."""
    backend.add_fact(FactRecord(content="Active fact", source="test"))
    superseded = backend.add_fact(FactRecord(content="Superseded fact", source="test"))
    backend.invalidate_fact(superseded.id, status=FactStatus.SUPERSEDED, note="old")

    results = backend.search(include_invalidated=True)
    assert len(results) == 2


def test_invalidate_fact_creates_bidirectional_relations(backend):
    """E24.1 AC-5: invalidate_fact creates superseded_by/supersedes relations."""
    old_fact = backend.add_fact(FactRecord(content="Old fact", source="test"))
    new_fact = backend.add_fact(FactRecord(content="New fact", source="test"))

    result = backend.invalidate_fact(
        old_fact.id,
        status=FactStatus.SUPERSEDED,
        note="replaced by new",
        superseded_by=new_fact.id,
    )

    assert result is not None
    assert result.status == FactStatus.SUPERSEDED
    assert result.superseded_by == new_fact.id
    assert result.invalidation_note == "replaced by new"
    assert result.invalidated_at is not None

    retrieved_old = backend.get_fact(old_fact.id)
    assert retrieved_old is not None
    superseded_by_rels = [r for r in retrieved_old.relations if r.relation_type == "superseded_by"]
    assert len(superseded_by_rels) == 1
    assert superseded_by_rels[0].target_id == new_fact.id

    retrieved_new = backend.get_fact(new_fact.id)
    assert retrieved_new is not None
    supersedes_rels = [r for r in retrieved_new.relations if r.relation_type == "supersedes"]
    assert len(supersedes_rels) == 1
    assert supersedes_rels[0].target_id == old_fact.id


def test_invalidate_fact_nonexistent_returns_none(backend):
    """E24.1: invalidate_fact returns None for unknown fact_id."""
    result = backend.invalidate_fact(uuid4(), status=FactStatus.INVALIDATED, note="n/a")
    assert result is None


def test_invalidate_fact_without_superseded_by(backend):
    """E24.1: invalidation without superseded_by sets status fields only."""
    fact = backend.add_fact(FactRecord(content="Disputed fact", source="test"))
    result = backend.invalidate_fact(fact.id, status=FactStatus.DISPUTED, note="doubted")

    assert result is not None
    assert result.status == FactStatus.DISPUTED
    assert result.superseded_by is None
    assert result.invalidation_note == "doubted"
    # DISPUTED populates ``disputed_at`` instead of ``invalidated_at``.
    assert result.disputed_at is not None
    assert result.invalidated_at is None

    retrieved = backend.get_fact(fact.id)
    assert retrieved is not None
    assert len([r for r in retrieved.relations if r.relation_type == "superseded_by"]) == 0


def test_invalidate_fact_invalidated_status_sets_invalidated_at(backend):
    """INVALIDATED / SUPERSEDED populate ``invalidated_at``, not ``disputed_at``."""
    fact = backend.add_fact(FactRecord(content="To be retracted", source="test"))
    result = backend.invalidate_fact(fact.id, status=FactStatus.INVALIDATED, note="wrong")

    assert result is not None
    assert result.status == FactStatus.INVALIDATED
    assert result.invalidated_at is not None
    assert result.disputed_at is None


def test_list_invalidated(backend):
    """E24.1: list_invalidated returns only non-ACTIVE facts sorted by invalidated_at desc."""
    f1 = backend.add_fact(FactRecord(content="Fact 1", source="test"))
    f2 = backend.add_fact(FactRecord(content="Fact 2", source="test"))
    backend.add_fact(FactRecord(content="Active fact", source="test"))

    backend.invalidate_fact(f1.id, status=FactStatus.SUPERSEDED, note="old")
    backend.invalidate_fact(f2.id, status=FactStatus.INVALIDATED, note="wrong")

    invalidated = backend.list_invalidated()
    assert len(invalidated) == 2
    assert invalidated[0].id == f2.id
    assert invalidated[1].id == f1.id


def test_list_invalidated_with_since_filter(backend):
    """E24.1: list_invalidated with since filter."""
    from datetime import UTC, datetime

    f1 = backend.add_fact(FactRecord(content="Old invalidated", source="test"))
    backend.invalidate_fact(f1.id, status=FactStatus.SUPERSEDED, note="old")

    f2 = backend.add_fact(FactRecord(content="New invalidated", source="test"))
    backend.invalidate_fact(f2.id, status=FactStatus.INVALIDATED, note="new")

    all_invalidated = backend.list_invalidated()
    assert len(all_invalidated) == 2

    earliest = min(f.invalidated_at for f in all_invalidated if f.invalidated_at is not None)
    filtered = backend.list_invalidated(since=earliest)
    assert len(filtered) >= 1

    future = datetime(2099, 1, 1, tzinfo=UTC)
    assert len(backend.list_invalidated(since=future)) == 0


def test_invalidate_lifecycle(backend):
    """E24.1: full lifecycle — add, invalidate, search, list_invalidated."""
    fact = backend.add_fact(FactRecord(content="Lifecycle test", source="test"))
    assert len(backend.search(query="lifecycle")) == 1

    backend.invalidate_fact(fact.id, status=FactStatus.SUPERSEDED, note="done")
    assert len(backend.search(query="lifecycle")) == 0
    assert len(backend.search(query="lifecycle", include_invalidated=True)) == 1
    assert len(backend.list_invalidated()) == 1
