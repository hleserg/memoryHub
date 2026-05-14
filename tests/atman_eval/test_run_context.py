from __future__ import annotations


def test_run_context_to_db_metadata_contains_expected_fields() -> None:
    from atman.eval.run_context import RunContext

    context = RunContext.create(
        benchmark_key="noop",
        seed=7,
        git_sha="abc123",
        extra_metadata={"suite": "smoke"},
    )
    metadata = context.to_db_metadata()

    assert metadata["app_run_id"] == context.run_id
    assert metadata["git_sha"] == "abc123"
    assert metadata["seed"] == 7
    assert metadata["extra"] == {"suite": "smoke"}
    assert "python_version" in metadata
