"""Tests page: run tests and view results."""

from __future__ import annotations

import streamlit as st

from atman.tui.repo_root import find_repo_root
from atman.web_dashboard.utils import pytest_cmd, run_command_sync

st.set_page_config(page_title="Tests - Atman Dashboard", page_icon="🧪", layout="wide")

# Find repository root
try:
    repo_root = find_repo_root()
except FileNotFoundError:
    st.error("Repository root not found.")
    st.stop()

st.title("🧪 Tests")
st.markdown("Запуск и просмотр результатов тестов")
st.divider()

# Test options
st.markdown("### ⚙️ Настройки тестов")

col1, col2, col3 = st.columns(3)

with col1:
    test_suite = st.selectbox(
        "Набор тестов:",
        options=["Все тесты (tests/)", "Только unit тесты", "Только integration тесты"],
        index=0,
    )

with col2:
    verbose = st.checkbox("Подробный вывод (-v)", value=True)
    coverage = st.checkbox("С покрытием (--cov)", value=True)

with col3:
    parallel = st.checkbox("Параллельно (-n auto)", value=False)
    fail_fast = st.checkbox("Остановить на первой ошибке (-x)", value=False)

st.divider()

# Run tests
col1, col2, col3 = st.columns(3)

with col1:
    run_tests = st.button("▶️ Запустить тесты", use_container_width=True, type="primary")

with col2:
    run_quick = st.button("⚡ Быстрый прогон (-q)", use_container_width=True)

with col3:
    if st.button("🗑️ Очистить результаты", use_container_width=True):
        if "test_output" in st.session_state:
            del st.session_state["test_output"]
        if "test_exit_code" in st.session_state:
            del st.session_state["test_exit_code"]
        st.rerun()

# Build command
if run_tests or run_quick:
    # Base path
    if test_suite == "Только unit тесты":
        test_path = "tests/unit/"
    elif test_suite == "Только integration тесты":
        test_path = "tests/integration/"
    else:
        test_path = "tests/"

    # Build arguments
    args = [test_path]

    if run_quick:
        args.append("-q")
    else:
        if verbose:
            args.append("-v")
        if coverage:
            args.extend(["--cov=atman", "--cov-fail-under=90", "--cov-report=term-missing"])
        if parallel:
            args.extend(["-n", "auto"])
        if fail_fast:
            args.append("-x")

    cmd = pytest_cmd(*args)

    st.markdown("### 🔄 Выполнение")
    st.code(" ".join(cmd))

    with st.spinner("Запуск тестов... Это может занять некоторое время."):
        exit_code, output = run_command_sync(cmd, repo_root)

    # Store results in session state
    st.session_state["test_output"] = output
    st.session_state["test_exit_code"] = exit_code

    st.rerun()

# Display results
if "test_output" in st.session_state and "test_exit_code" in st.session_state:
    st.divider()
    exit_code = st.session_state["test_exit_code"]
    output = st.session_state["test_output"]

    # Result summary
    st.markdown("### 📊 Результаты")

    if exit_code == 0:
        st.success(f"✅ Все тесты пройдены успешно! (exit {exit_code})")
    else:
        st.error(f"❌ Тесты завершились с ошибками (exit {exit_code})")

    # Parse summary (simplified)
    if "passed" in output.lower():
        lines = output.split("\n")
        for line in lines:
            if "passed" in line.lower() and "failed" in line.lower():
                st.info(f"📈 {line.strip()}")
                break

    # Coverage info
    if "TOTAL" in output and "%" in output:
        lines = output.split("\n")
        for _i, line in enumerate(lines):
            if "TOTAL" in line:
                st.info(f"📊 Покрытие кода: {line.strip()}")
                break

    # Full output
    st.markdown("### 📋 Полный вывод")

    # Tabs for different views
    tab1, tab2 = st.tabs(["Все", "Только ошибки"])

    with tab1, st.container(height=600, border=True):
        st.code(output, language="text")

    with tab2:
        # Extract failure lines
        error_lines = []
        in_failure = False
        for line in output.split("\n"):
            if "FAILED" in line or "ERROR" in line or "=" * 10 in line:
                in_failure = True
            if in_failure:
                error_lines.append(line)
            if line.strip().startswith("=") and "short test summary" in line.lower():
                in_failure = False

        if error_lines:
            with st.container(height=600, border=True):
                st.code("\n".join(error_lines), language="text")
        else:
            st.success("🎉 Нет ошибок!")

# Info section
st.divider()
st.markdown("### ℹ️ Информация")

with st.expander("Доступные опции pytest"):
    st.markdown(
        """
        - `-v` — подробный вывод (verbose)
        - `-q` — краткий вывод (quiet)
        - `--cov=atman` — измерение покрытия кода
        - `--cov-fail-under=90` — требовать минимум 90% покрытия
        - `-n auto` — параллельный запуск тестов
        - `-x` — остановиться на первой ошибке (fail-fast)
        """
    )
