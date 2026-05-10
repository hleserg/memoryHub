"""
Unit-тесты для FileBackend.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

import pytest

from atman.adapters.memory import FileBackend
from atman.core.models import FactRecord, FactStatus


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


# --- SYSTEM_MAP §4.3 / §5.3: malformed JSONL handling ---


def test_read_facts_skips_malformed_lines_without_data_loss(temp_file):
    """SYSTEM_MAP §4.3: malformed JSONL lines are warned and skipped, not silently dropped."""
    valid = FactRecord(content="Хороший факт", source="test")
    temp_file.write_text(
        valid.model_dump_json() + "\n" + "this is not json\n" + '{"oops": "not a fact record"}\n',
        encoding="utf-8",
    )

    with pytest.warns(RuntimeWarning, match="Skipping malformed fact"):
        backend = FileBackend(temp_file)

    # Valid fact survived.
    loaded = backend.get_fact(valid.id)
    assert loaded is not None
    assert loaded.content == "Хороший факт"

    # Adding a new fact after recovery still works and preserves the valid one.
    extra = FactRecord(content="Ещё один", source="test")
    backend.add_fact(extra)
    assert backend.get_fact(extra.id) is not None
    assert backend.get_fact(valid.id) is not None


def test_add_fact_duplicate_id_raises_with_clear_message(temp_file, backend):
    """SYSTEM_MAP §4.2: duplicate fact id is rejected with an explicit error mentioning the UUID."""
    fact = FactRecord(content="Уникальный факт", source="test")
    backend.add_fact(fact)

    with pytest.raises(ValueError, match=str(fact.id)):
        backend.add_fact(fact)


# --- E24.1: FactStatus, invalidation, search filtering ---


def test_search_excludes_invalidated_by_default(backend):
    """E24.1 AC-3: search() returns only ACTIVE facts when invalidated facts exist."""
    active = backend.add_fact(FactRecord(content="Active fact", source="test"))
    superseded = backend.add_fact(FactRecord(content="Superseded fact", source="test"))
    backend.invalidate_fact(superseded.id, status=FactStatus.SUPERSEDED, note="old")

    results = backend.search()
    assert len(results) == 1
    assert results[0].id == active.id


def test_search_includes_invalidated_when_requested(backend):
    """E24.1 AC-4: search(include_invalidated=True) returns all facts including SUPERSEDED."""
    backend.add_fact(FactRecord(content="Active fact", source="test"))
    superseded = backend.add_fact(FactRecord(content="Superseded fact", source="test"))
    backend.invalidate_fact(superseded.id, status=FactStatus.SUPERSEDED, note="old")

    results = backend.search(include_invalidated=True)
    assert len(results) == 2


def test_invalidate_fact_creates_bidirectional_relations(backend):
    """E24.1 AC-5: invalidate_fact with superseded_by creates relations on both facts."""
    old_fact = backend.add_fact(FactRecord(content="Old fact", source="test"))
    new_fact = backend.add_fact(FactRecord(content="New fact", source="test"))

    result = backend.invalidate_fact(
        old_fact.id,
        status=FactStatus.SUPERSEDED,
        note="replaced",
        superseded_by=new_fact.id,
    )

    assert result is not None
    assert result.status == FactStatus.SUPERSEDED
    assert result.superseded_by == new_fact.id
    assert result.invalidation_note == "replaced"
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
    from uuid import uuid4

    result = backend.invalidate_fact(uuid4(), status=FactStatus.INVALIDATED, note="n/a")
    assert result is None


def test_invalidate_fact_persistence(temp_file):
    """E24.1: invalidation state persists across FileBackend instances."""
    backend1 = FileBackend(temp_file)
    fact = backend1.add_fact(FactRecord(content="Persistent invalidation", source="test"))
    new_fact = backend1.add_fact(FactRecord(content="Replacement", source="test"))
    backend1.invalidate_fact(
        fact.id,
        status=FactStatus.SUPERSEDED,
        note="persisted",
        superseded_by=new_fact.id,
    )

    backend2 = FileBackend(temp_file)
    retrieved = backend2.get_fact(fact.id)
    assert retrieved is not None
    assert retrieved.status == FactStatus.SUPERSEDED
    assert retrieved.invalidation_note == "persisted"
    assert retrieved.superseded_by == new_fact.id
    assert retrieved.invalidated_at is not None

    superseded_by_rels = [r for r in retrieved.relations if r.relation_type == "superseded_by"]
    assert len(superseded_by_rels) == 1


def test_list_invalidated(backend):
    """E24.1: list_invalidated returns non-ACTIVE facts sorted by invalidated_at desc."""
    f1 = backend.add_fact(FactRecord(content="Fact 1", source="test"))
    f2 = backend.add_fact(FactRecord(content="Fact 2", source="test"))
    backend.add_fact(FactRecord(content="Active fact", source="test"))

    backend.invalidate_fact(f1.id, status=FactStatus.SUPERSEDED, note="old")
    backend.invalidate_fact(f2.id, status=FactStatus.INVALIDATED, note="wrong")

    invalidated = backend.list_invalidated()
    assert len(invalidated) == 2
    assert invalidated[0].id == f2.id
    assert invalidated[1].id == f1.id


def test_list_invalidated_includes_disputed_facts(backend):
    """DISPUTED facts must appear in list_invalidated and respect since-filter."""
    from datetime import UTC, datetime, timedelta

    fact = backend.add_fact(FactRecord(content="To be disputed", source="test"))
    backend.invalidate_fact(fact.id, status=FactStatus.DISPUTED, note="not sure")

    listed = backend.list_invalidated()
    assert len(listed) == 1
    assert listed[0].id == fact.id
    assert listed[0].status == FactStatus.DISPUTED

    listed_since_past = backend.list_invalidated(since=datetime(2000, 1, 1, tzinfo=UTC))
    assert len(listed_since_past) == 1

    listed_since_future = backend.list_invalidated(since=datetime.now(UTC) + timedelta(days=1))
    assert listed_since_future == []


def test_invalidate_lifecycle(backend):
    """E24.1: full lifecycle — add, invalidate, search, list_invalidated."""
    fact = backend.add_fact(FactRecord(content="Lifecycle test", source="test"))
    assert len(backend.search(query="lifecycle")) == 1

    backend.invalidate_fact(fact.id, status=FactStatus.SUPERSEDED, note="done")
    assert len(backend.search(query="lifecycle")) == 0
    assert len(backend.search(query="lifecycle", include_invalidated=True)) == 1
    assert len(backend.list_invalidated()) == 1


def test_invalidate_terminal_status_drops_salience_to_zero(backend):
    """Terminal lifecycle states (INVALIDATED / SUPERSEDED) zero salience.

    Mirrors :meth:`InMemoryBackend.invalidate_fact` and
    :meth:`FactRecord.invalidate` so consumers see consistent post-invalidation
    salience regardless of which adapter is wired in.
    """
    high_salience = FactRecord(content="High salience", source="test", salience=0.9)
    fact = backend.add_fact(high_salience)
    assert fact.salience == pytest.approx(0.9)

    invalidated = backend.invalidate_fact(fact.id, status=FactStatus.INVALIDATED, note="stale")
    assert invalidated is not None
    assert invalidated.salience == 0.0

    superseded_target = backend.add_fact(FactRecord(content="Replaces", source="test"))
    superseded_source = backend.add_fact(
        FactRecord(content="Source 2", source="test", salience=0.8)
    )
    result = backend.invalidate_fact(
        superseded_source.id,
        status=FactStatus.SUPERSEDED,
        note="replaced",
        superseded_by=superseded_target.id,
    )
    assert result is not None
    assert result.salience == 0.0


def test_invalidate_disputed_keeps_salience(backend):
    """DISPUTED is provisional; salience is intentionally preserved."""
    fact = backend.add_fact(FactRecord(content="Maybe wrong", source="test", salience=0.7))

    disputed = backend.invalidate_fact(fact.id, status=FactStatus.DISPUTED, note="under review")
    assert disputed is not None
    assert disputed.salience == pytest.approx(0.7)


def test_list_invalidated_sort_handles_missing_lifecycle_timestamp(backend):
    """Sort key uses a UTC-aware fallback so naive/aware comparison can't crash.

    A non-ACTIVE fact constructed without a lifecycle timestamp would otherwise
    blow up the sort with ``TypeError: can't compare offset-naive and
    offset-aware datetimes``.
    """
    seeded = backend.add_fact(FactRecord(content="seeded", source="test"))
    backend.invalidate_fact(seeded.id, status=FactStatus.INVALIDATED, note="real")

    # Inject a non-ACTIVE fact with no lifecycle timestamp directly via the
    # in-memory map. This simulates legacy data where timestamps were never
    # populated; the sort fallback must not crash.
    legacy = FactRecord(content="legacy", source="test", status=FactStatus.INVALIDATED)
    backend._facts[legacy.id] = legacy

    listed = backend.list_invalidated()
    assert len(listed) == 2


# ---------------------------------------------------------------------------
# E24.3: confirm_fact / decay_stale_facts (disk persistence + cache refresh)
# ---------------------------------------------------------------------------


def test_confirm_fact_persists_to_disk(backend, temp_file):
    """confirm_fact: a fresh FileBackend reading the same file sees the bump."""
    fact = backend.add_fact(FactRecord(content="Persist me", source="t", salience=0.4))
    assert backend.confirm_fact(fact.id) is True

    # Independent reader proves the change reached disk, not just the cache.
    reader = FileBackend(temp_file)
    refreshed = reader.get_fact(fact.id)
    assert refreshed is not None
    assert refreshed.confirmation_count == 1
    assert refreshed.last_confirmed_at is not None
    assert refreshed.salience == pytest.approx(0.5)


def test_confirm_fact_returns_false_for_unknown_id(backend):
    """confirm_fact: missing ID is a clean ``False`` and does not write."""
    assert backend.confirm_fact(uuid4()) is False


def test_decay_stale_facts_persists_and_skips_non_active(backend, temp_file):
    """decay_stale_facts: persists changes, skips non-ACTIVE facts."""
    # Cutoff in the past so ``confirm_fact(fresh.id)`` lands after it.
    before_cutoff = datetime.now(UTC) - timedelta(hours=1)
    stale = backend.add_fact(FactRecord(content="Stale", source="t", salience=0.8))
    fresh = backend.add_fact(FactRecord(content="Fresh", source="t", salience=0.8))
    backend.confirm_fact(fresh.id)
    invalidated = backend.add_fact(
        FactRecord(content="Stale invalidated", source="t", salience=0.8)
    )
    backend.invalidate_fact(invalidated.id, status=FactStatus.INVALIDATED, note="gone")

    decayed = backend.decay_stale_facts(before=before_cutoff, decay_factor=0.5)
    assert decayed == 1

    reader = FileBackend(temp_file)
    refreshed_stale = reader.get_fact(stale.id)
    refreshed_fresh = reader.get_fact(fresh.id)
    refreshed_inv = reader.get_fact(invalidated.id)
    assert refreshed_stale is not None
    assert refreshed_fresh is not None
    assert refreshed_inv is not None
    assert refreshed_stale.salience == pytest.approx(0.4)
    # confirm() bumped fresh to 0.9; decay does not touch it.
    assert refreshed_fresh.salience == pytest.approx(0.9)
    # Invalidated facts are zeroed by invalidate_fact, not by decay.
    assert refreshed_inv.salience == 0.0


def test_decay_stale_facts_skips_disk_write_when_count_is_zero(backend, temp_file):
    """decay_stale_facts: when no fact decays, mtime stays stable (no write)."""
    fact = backend.add_fact(FactRecord(content="Just confirmed", source="t", salience=0.6))
    backend.confirm_fact(fact.id)

    mtime_before = temp_file.stat().st_mtime_ns

    decayed = backend.decay_stale_facts(
        before=datetime.now(UTC) - timedelta(days=30), decay_factor=0.5
    )
    assert decayed == 0
    # The implementation guards _save_facts behind `if count > 0`, so the
    # JSONL file must not be rewritten.
    assert temp_file.stat().st_mtime_ns == mtime_before
