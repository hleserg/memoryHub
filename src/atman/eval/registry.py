"""Simple benchmark registry for eval runner."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from atman.eval.run_context import RunContext
    from atman.eval.runner_core import BenchmarkResult

BenchmarkFn = Callable[["RunContext"], "BenchmarkResult"]

_REGISTRY: dict[str, BenchmarkFn] = {}


def register(benchmark_key: str) -> Callable[[BenchmarkFn], BenchmarkFn]:
    """Register benchmark implementation under a unique key."""

    def decorator(func: BenchmarkFn) -> BenchmarkFn:
        if benchmark_key in _REGISTRY:
            raise ValueError(f"Benchmark already registered: {benchmark_key}")
        _REGISTRY[benchmark_key] = func
        return func

    return decorator


def get(benchmark_key: str) -> BenchmarkFn:
    """Get benchmark callable or raise a helpful error."""
    if benchmark_key not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY)) or "<none>"
        raise KeyError(f"Unknown benchmark: {benchmark_key}. Available: {available}")
    return _REGISTRY[benchmark_key]


def list_benchmarks() -> list[str]:
    return sorted(_REGISTRY)


def clear() -> None:
    """Test helper: clear registry state."""
    _REGISTRY.clear()
