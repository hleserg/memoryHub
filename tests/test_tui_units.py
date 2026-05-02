"""Unit tests for Atman developer TUI helpers (no Textual event loop)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from atman.tui.cmd import pytest_cmd, python_script_cmd, uv_or_python_argv
from atman.tui.features_registry import FEATURES, get_feature
from atman.tui.pytest_utils import (
    classify_nodeids,
    extract_failure_only_log,
    junit_failure_error_count,
    parse_collect_only,
    parse_coverage_total_percent,
    parse_junit_counts,
    parse_summary_line,
    parse_verbose_result_line,
)
from atman.tui.repo_root import find_repo_root


def test_find_repo_root_explicit(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    assert find_repo_root(tmp_path) == tmp_path


def test_find_repo_root_walks_parents(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert find_repo_root(nested) == tmp_path


def test_find_repo_root_raises_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    orphan = tmp_path / "nowhere"
    orphan.mkdir()

    def _only_orphan(start: Path | None) -> list[Path]:
        return [orphan.resolve()]

    monkeypatch.setattr("atman.tui.repo_root._candidates", _only_orphan)
    with pytest.raises(FileNotFoundError):
        find_repo_root(orphan)


def test_parse_collect_only_filters_noise() -> None:
    sample = "tests/a.py::test_one\ntests/a.py::test_two\n116 tests collected in 0.37s\n"
    ids = parse_collect_only(sample)
    assert ids == ["tests/a.py::test_one", "tests/a.py::test_two"]


def test_parse_collect_only_skips_collection_error_and_plain_lines() -> None:
    sample = (
        "ERROR collecting foo\n"
        "error during collection: boom\n"
        "not a test line\n"
        "=====\n"
        "tests/a.py::test_one\n"
    )
    assert parse_collect_only(sample) == ["tests/a.py::test_one"]


def test_parse_summary_line_counts_extras() -> None:
    log = "=== 1 failed, 2 passed, 1 skipped, 3 deselected, 1 xfailed, 1 xpassed in 9.99s ==="
    s = parse_summary_line(log)
    assert s is not None
    assert s.failed == 1
    assert s.passed == 2
    assert s.skipped == 1
    assert s.deselected == 3
    assert s.xfailed == 1
    assert s.xpassed == 1
    assert s.duration_seconds == pytest.approx(9.99)


def test_extract_failure_errors_section() -> None:
    log = """
=================================== ERRORS ====================================
____________________ ERROR collecting tests/broken.py _________________________
ImportError while loading conftest
=========================== short test summary info ============================
ERROR tests/broken.py
============================== 1 error in 0.2s ===============================
"""
    slim = extract_failure_only_log(log)
    assert "ERRORS" in slim
    assert "short test summary" in slim.lower()


def test_junit_failure_error_count_sums(tmp_path: Path) -> None:
    p = tmp_path / "j.xml"
    p.write_text(
        '<?xml version="1.0"?><testsuites>'
        '<testsuite tests="2" failures="1" errors="1" skipped="0" name="pytest"/>'
        "</testsuites>",
        encoding="utf-8",
    )
    assert junit_failure_error_count(p) == 2


def test_parse_verbose_result_line() -> None:
    line = "tests/test_models.py::test_fact_record_creation PASSED                   [100%]"
    assert parse_verbose_result_line(line) == (
        "tests/test_models.py::test_fact_record_creation",
        "PASSED",
    )
    assert parse_verbose_result_line("not a result") is None


def test_classify_nodeids() -> None:
    nodeids = [
        "tests/test_x.py::test_plain",
        "tests/test_x.py::TestC::test_method",
    ]
    k = classify_nodeids(nodeids)
    assert k.total == 2
    assert k.plain_functions == 1
    assert k.class_methods == 1


def test_parse_summary_line() -> None:
    log = "\n".join(
        [
            "============================== 2 failed, 5 passed in 1.23s ===============================",
        ]
    )
    s = parse_summary_line(log)
    assert s is not None
    assert s.passed == 5
    assert s.failed == 2
    assert s.duration_seconds == pytest.approx(1.23)


def test_parse_coverage_total_percent() -> None:
    block = "TOTAL                                                        657    541    152      0    15%\n"
    assert parse_coverage_total_percent(block) == pytest.approx(15.0)
    assert parse_coverage_total_percent("no table here") is None


def test_parse_summary_line_none() -> None:
    assert parse_summary_line("no banner here") is None


def test_parse_junit_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "nope.xml"
    assert parse_junit_counts(missing) == {
        "tests": 0,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
    }


def test_parse_junit_malformed(tmp_path: Path) -> None:
    bad = tmp_path / "bad.xml"
    bad.write_text("not xml", encoding="utf-8")
    assert parse_junit_counts(bad) == {
        "tests": 0,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
    }


def test_extract_failure_fallback_failed_lines() -> None:
    log = "FAILED tests/x.py::test_a - boom\n============================== 1 failed in 0.1s ======"
    slim = extract_failure_only_log(log)
    assert "FAILED tests/x.py::test_a" in slim


def test_extract_failure_only_log() -> None:
    log = """
=================================== FAILURES ===================================
___________________________________ test_bad ___________________________________

    assert False
E   assert False
=========================== short test summary info ============================
FAILED tmp/t.py::test_bad - assert False
============================== 1 failed in 0.07s ===============================
"""
    slim = extract_failure_only_log(log)
    assert "FAILURES" in slim
    assert "test_bad" in slim
    assert "short test summary" in slim.lower()


def test_extract_failure_only_empty_when_green() -> None:
    log = "============================== 1 passed in 0.1s =============================="
    assert extract_failure_only_log(log) == ""


def test_junit_parse_counts(tmp_path: Path) -> None:
    p = tmp_path / "out.xml"
    p.write_text(
        '<?xml version="1.0"?><testsuites>'
        '<testsuite tests="3" failures="1" errors="1" skipped="0" name="pytest"/>'
        "</testsuites>",
        encoding="utf-8",
    )
    c = parse_junit_counts(p)
    assert c["tests"] == 3
    assert c["failures"] == 1
    assert c["errors"] == 1


def test_features_registry() -> None:
    assert len(FEATURES) >= 2
    f = get_feature("factual-memory")
    assert f is not None
    assert "Factual" in f.title
    assert f.doc_dir.startswith("docs/features/")
    assert get_feature("no-such-slug") is None


def test_python_script_cmd_without_uv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("atman.tui.cmd.shutil.which", lambda _name: None)
    d = python_script_cmd("src/demo.py")
    assert d[0] == sys.executable
    assert d[1:] == ["src/demo.py"]


def test_uv_fallback_non_pytest_python(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("atman.tui.cmd.shutil.which", lambda _name: None)
    assert uv_or_python_argv("foo", "bar") == [sys.executable, "foo", "bar"]


def test_cmd_helpers_return_non_empty() -> None:
    p = pytest_cmd("tests/", "-q")
    assert "pytest" in p
    demo = python_script_cmd("src/demo.py")
    assert demo[-1] == "src/demo.py"
    alt = uv_or_python_argv("pytest", "-q")
    assert alt[0] == "uv" or "-m" in alt


def test_pytest_cmd_falls_back_without_uv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("atman.tui.cmd.shutil.which", lambda _name: None)
    p = pytest_cmd("-q")
    assert p[0] == sys.executable
    assert p[1:3] == ["-m", "pytest"]


def test_uv_or_python_argv_pytest_python_paths_without_uv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("atman.tui.cmd.shutil.which", lambda _name: None)
    assert uv_or_python_argv("pytest", "-q") == [sys.executable, "-m", "pytest", "-q"]
    assert uv_or_python_argv("python", "demo.py") == [sys.executable, "demo.py"]


def test_tests_tab_does_not_use_message_pump_running_for_pytest_guard() -> None:
    """Textual sets MessagePump._running=True while the widget processes messages.

    Using the same name for a pytest in-flight flag makes ``run_pytest_suite`` exit
    immediately on every click.
    """
    import inspect

    from atman.tui.tests_tab import TestsTab

    src = inspect.getsource(TestsTab.run_pytest_suite)
    assert "_pytest_busy" in src
    assert "self._running" not in src
