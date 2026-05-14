"""Atman evaluation subsystem.

Optional namespace — not part of the production install.
Install with: pip install 'atman[eval]'

This module is intentionally isolated from the production code in
src/atman/{factual_memory,identity_store,...}. Production code MUST NOT
import from atman.eval; this is enforced by import-linter (.importlinter)
and verified by `make verify-prod-isolation`.
"""

import warnings
from importlib import import_module

from atman.eval._deps_check import _check_eval_deps_installed

_check_eval_deps_installed()


def _load_builtin_benchmarks() -> None:
    try:
        import_module("atman.eval.benchmarks")
    except Exception as exc:
        warnings.warn(
            f"Failed to import atman.eval.benchmarks: {exc}", RuntimeWarning, stacklevel=2
        )


_load_builtin_benchmarks()

__all__ = [
    "BenchmarkItemResult",
    "BenchmarkResult",
    "BenchmarkRunOutcome",
    "RunContext",
    "RunnerCore",
    "get",
    "list_benchmarks",
    "register",
]


def __getattr__(name: str) -> object:
    if name in {"get", "list_benchmarks", "register"}:
        module = import_module("atman.eval.registry")
        return getattr(module, name)
    if name == "RunContext":
        module = import_module("atman.eval.run_context")
        return getattr(module, name)
    if name in {"BenchmarkItemResult", "BenchmarkResult", "BenchmarkRunOutcome", "RunnerCore"}:
        module = import_module("atman.eval.runner_core")
        return getattr(module, name)
    raise AttributeError(name)
