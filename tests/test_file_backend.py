"""
Unit-тесты для FileBackend.
"""

from pathlib import Path
from tempfile import NamedTemporaryFile

import pytest

from atman.adapters.memory import FileBackend
from atman.core.models import FactRecord


@pytest.fixture
def temp_file():
    """Фикстура с временным файлом."""
    with NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        filepath = Path(f.name)
    lockpath = filepath.with_name(f".{filepath.name}.lock")

    yield filepath

    if filepath.exists():
        filepath.unlink()
    if lockpath.exists():
        lockpath.unlink()


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
    assert retrieved is not None
    assert len(retrieved.relations) == 1


def test_link_persistence(temp_file):
    """Тест персистентности связей."""
    backend1 = FileBackend(temp_file)
    fact1 = backend1.add_fact(FactRecord(content="Факт 1", source="test"))
    fact2 = backend1.add_fact(FactRecord(content="Факт 2", source="test"))
    backend1.link(fact1.id, fact2.id, "related")

    backend2 = FileBackend(temp_file)
    retrieved = backend2.get_fact(fact1.id)
    assert retrieved is not None

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
        fact = backend.add_fact(FactRecord(content=f"Факт {i}", source="test", tags=[f"tag{i}"]))
        facts.append(fact)

    backend2 = FileBackend(temp_file)
    assert backend2.count() == 10

    for original in facts:
        retrieved = backend2.get_fact(original.id)
        assert retrieved is not None
        assert retrieved.content == original.content


def test_failed_save_keeps_existing_file_and_memory_state(temp_file):
    """Неуспешное сохранение не должно портить уже записанные факты."""
    backend = FileBackend(temp_file)
    original = backend.add_fact(FactRecord(content="Безопасный факт", source="test"))
    original_file_content = temp_file.read_text(encoding="utf-8")

    invalid_replacement = original.model_copy(
        update={"content": "Несериализуемый факт", "metadata": {"bad": object()}},
        deep=True,
    )

    with pytest.raises(Exception):
        backend.add_fact(invalid_replacement)

    assert temp_file.read_text(encoding="utf-8") == original_file_content
    fact_after_fail = backend.get_fact(original.id)
    assert fact_after_fail is not None
    assert fact_after_fail.content == "Безопасный факт"

    reloaded = FileBackend(temp_file)
    fact_reloaded = reloaded.get_fact(original.id)
    assert fact_reloaded is not None
    assert fact_reloaded.content == "Безопасный факт"


def test_save_preserves_existing_file_permissions(temp_file):
    """Атомарная замена не должна раскрывать приватный файл."""
    temp_file.chmod(0o600)
    backend = FileBackend(temp_file)

    backend.add_fact(FactRecord(content="Приватный факт", source="test"))

    assert (temp_file.stat().st_mode & 0o777) == 0o600


def test_save_creates_new_file_with_private_permissions(temp_file):
    """Новый файл хранилища должен создаваться закрытым по умолчанию."""
    temp_file.unlink()
    backend = FileBackend(temp_file)

    backend.add_fact(FactRecord(content="Новый приватный факт", source="test"))

    assert (temp_file.stat().st_mode & 0o777) == 0o600


def test_multiple_instances_do_not_lose_added_facts(temp_file):
    """Два экземпляра не должны перетирать факты друг друга при сохранении."""
    backend1 = FileBackend(temp_file)
    backend2 = FileBackend(temp_file)

    fact1 = backend1.add_fact(FactRecord(content="Факт из первого backend", source="test"))
    fact2 = backend2.add_fact(FactRecord(content="Факт из второго backend", source="test"))

    reloaded = FileBackend(temp_file)
    assert reloaded.count() == 2
    r1 = reloaded.get_fact(fact1.id)
    r2 = reloaded.get_fact(fact2.id)
    assert r1 is not None
    assert r2 is not None
    assert r1.content == fact1.content
    assert r2.content == fact2.content


def test_multiple_instances_do_not_lose_links(temp_file):
    """Связь из одного экземпляра не должна удалять факт из другого экземпляра."""
    backend1 = FileBackend(temp_file)
    backend2 = FileBackend(temp_file)

    fact1 = backend1.add_fact(FactRecord(content="Исходный факт", source="test"))
    fact2 = backend2.add_fact(FactRecord(content="Целевой факт", source="test"))

    assert backend1.link(fact1.id, fact2.id, "related")

    reloaded = FileBackend(temp_file)
    assert reloaded.count() == 2
    reloaded_fact2 = reloaded.get_fact(fact2.id)
    assert reloaded_fact2 is not None
    assert reloaded_fact2.content == fact2.content

    linked_fact = reloaded.get_fact(fact1.id)
    assert linked_fact is not None
    assert len(linked_fact.relations) == 1
    assert linked_fact.relations[0].target_id == fact2.id


def test_multiple_instances_preserve_links_added_to_same_fact(temp_file):
    """Последовательные связи из разных экземпляров не должны перетирать друг друга."""
    backend1 = FileBackend(temp_file)
    source = backend1.add_fact(FactRecord(content="Исходный факт", source="test"))
    target1 = backend1.add_fact(FactRecord(content="Первый целевой факт", source="test"))
    target2 = backend1.add_fact(FactRecord(content="Второй целевой факт", source="test"))
    backend2 = FileBackend(temp_file)

    assert backend1.link(source.id, target1.id, "related")
    assert backend2.link(source.id, target2.id, "caused")

    reloaded = FileBackend(temp_file)
    linked_fact = reloaded.get_fact(source.id)
    assert linked_fact is not None
    relation_targets = {relation.target_id for relation in linked_fact.relations}

    assert len(linked_fact.relations) == 2
    assert relation_targets == {target1.id, target2.id}
