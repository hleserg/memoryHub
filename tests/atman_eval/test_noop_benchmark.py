from __future__ import annotations


def test_noop_benchmark_returns_single_pass_item() -> None:
    from atman.eval.benchmarks.noop import run_noop
    from atman.eval.run_context import RunContext

    context = RunContext.create(benchmark_key="noop", seed=11, git_sha="abc")
    result = run_noop(context)

    assert len(result.items) == 1
    assert result.items[0].verdict == "pass"
    assert result.metadata["benchmark"] == "noop"
