"""Tests for SessionCache (memory optimization)."""

from __future__ import annotations

from uuid import uuid4

from atman.core.services.session_cache import SessionCache


def test_initial_state_is_empty():
    cache = SessionCache()
    assert cache.entity_resolutions == {}
    assert cache.rag_results == {}
    assert cache.dirty_entities == set()


def test_is_rag_cached_false_when_no_results():
    cache = SessionCache()
    assert not cache.is_rag_cached(uuid4())


def test_is_rag_cached_true_after_storing():
    cache = SessionCache()
    eid = uuid4()
    cache.rag_results[eid] = [1, 2, 3]
    assert cache.is_rag_cached(eid)


def test_invalidate_rag_removes_result_and_marks_dirty():
    cache = SessionCache()
    eid = uuid4()
    cache.rag_results[eid] = ["result"]
    cache.invalidate_rag(eid)
    assert eid in cache.dirty_entities
    assert eid not in cache.rag_results
    assert not cache.is_rag_cached(eid)


def test_invalidate_rag_on_unknown_entity_is_safe():
    cache = SessionCache()
    eid = uuid4()
    cache.invalidate_rag(eid)
    assert eid in cache.dirty_entities


def test_dirty_entity_not_cached_even_if_result_present():
    cache = SessionCache()
    eid = uuid4()
    cache.rag_results[eid] = ["stale"]
    cache.dirty_entities.add(eid)
    assert not cache.is_rag_cached(eid)


def test_stats_reflects_current_state():
    cache = SessionCache()
    eid = uuid4()
    cache.entity_resolutions["Alice"] = object()
    cache.rag_results[eid] = []
    cache.dirty_entities.add(uuid4())
    stats = cache.stats()
    assert stats["entity_cache_size"] == 1
    assert stats["rag_cache_size"] == 1
    assert stats["dirty_count"] == 1


def test_clear_resets_all_fields():
    cache = SessionCache()
    eid = uuid4()
    cache.entity_resolutions["Bob"] = object()
    cache.rag_results[eid] = []
    cache.dirty_entities.add(eid)
    cache.entity_resolutions.clear()
    cache.rag_results.clear()
    cache.dirty_entities.clear()
    assert cache.stats() == {"entity_cache_size": 0, "rag_cache_size": 0, "dirty_count": 0}
