from __future__ import annotations

import pytest


def test_registry_register_get_list_cycle() -> None:
    from atman.eval import registry
    from atman.eval.run_context import RunContext
    from atman.eval.runner_core import BenchmarkResult

    registry.clear()

    @registry.register("unit:test")
    def benchmark(_: RunContext) -> BenchmarkResult:
        return BenchmarkResult(items=[])

    assert registry.get("unit:test") is benchmark
    assert registry.list_benchmarks() == ["unit:test"]


def test_registry_duplicate_key_rejected() -> None:
    from atman.eval import registry
    from atman.eval.run_context import RunContext
    from atman.eval.runner_core import BenchmarkResult

    registry.clear()

    @registry.register("dup:test")
    def first(_: RunContext) -> BenchmarkResult:
        return BenchmarkResult(items=[])

    assert first is not None
    with pytest.raises(ValueError, match="Benchmark already registered"):

        @registry.register("dup:test")
        def second(_: RunContext) -> BenchmarkResult:
            return BenchmarkResult(items=[])

    registry.clear()


def test_registry_unknown_key_has_helpful_error() -> None:
    from atman.eval import registry

    registry.clear()
    with pytest.raises(KeyError, match="Unknown benchmark"):
        registry.get("missing")
