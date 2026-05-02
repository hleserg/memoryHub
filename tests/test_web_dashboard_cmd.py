"""Tests for web_dashboard.utils.cmd module."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

from atman.web_dashboard.utils.cmd import (
    demo_subprocess_env,
    get_demo_command,
    pytest_cmd,
    python_script_cmd,
)


def test_python_script_cmd_with_uv() -> None:
    """Test python_script_cmd when uv is available."""
    with patch("atman.web_dashboard.utils.cmd.which", return_value="/usr/bin/uv"):
        result = python_script_cmd("src/demo.py")
        assert result == ["uv", "run", "python", "src/demo.py"]


def test_python_script_cmd_without_uv() -> None:
    """Test python_script_cmd when uv is not available."""
    with patch("atman.web_dashboard.utils.cmd.which", return_value=None):
        result = python_script_cmd("src/demo.py")
        assert result == [sys.executable, "src/demo.py"]


def test_python_script_cmd_multiple_args() -> None:
    """Test python_script_cmd with multiple arguments."""
    with patch("atman.web_dashboard.utils.cmd.which", return_value=None):
        result = python_script_cmd("src/script.py", "--arg1", "--arg2")
        assert result == [sys.executable, "src/script.py", "--arg1", "--arg2"]


def test_pytest_cmd_with_uv() -> None:
    """Test pytest_cmd when uv is available."""
    with patch("atman.web_dashboard.utils.cmd.which", return_value="/usr/bin/uv"):
        result = pytest_cmd("tests/", "-v")
        assert result == ["uv", "run", "pytest", "tests/", "-v"]


def test_pytest_cmd_without_uv() -> None:
    """Test pytest_cmd when uv is not available."""
    with patch("atman.web_dashboard.utils.cmd.which", return_value=None):
        result = pytest_cmd("tests/", "-v")
        assert result == [sys.executable, "-m", "pytest", "tests/", "-v"]


def test_pytest_cmd_no_args() -> None:
    """Test pytest_cmd with no additional arguments."""
    with patch("atman.web_dashboard.utils.cmd.which", return_value=None):
        result = pytest_cmd()
        assert result == [sys.executable, "-m", "pytest"]


def test_demo_subprocess_env_paced_overrides_registry() -> None:
    """Button-selected paced mode must win over registry env (e.g. single-demo list)."""
    assert demo_subprocess_env({"ATMAN_DEMO_PACE": "off"}, paced=True) == {
        "ATMAN_DEMO_PACE": "1",
    }


def test_demo_subprocess_env_fast_overrides_registry() -> None:
    assert demo_subprocess_env({"ATMAN_DEMO_PACE": "1"}, paced=False) == {
        "ATMAN_DEMO_PACE": "off",
    }


def test_demo_subprocess_env_preserves_other_keys() -> None:
    assert demo_subprocess_env({"FOO": "bar"}, paced=False) == {
        "FOO": "bar",
        "ATMAN_DEMO_PACE": "off",
    }


def test_get_demo_command_paced() -> None:
    """Test get_demo_command with paced=True."""
    cmd, env = get_demo_command("src/demo.py", paced=True)

    # Check that we get a valid command list
    assert isinstance(cmd, list)
    assert len(cmd) >= 2
    assert "src/demo.py" in cmd

    # Check environment
    assert env == {"ATMAN_DEMO_PACE": "1"}


def test_get_demo_command_fast() -> None:
    """Test get_demo_command with paced=False."""
    cmd, env = get_demo_command("src/demo.py", paced=False)

    # Check that we get a valid command list
    assert isinstance(cmd, list)
    assert len(cmd) >= 2
    assert "src/demo.py" in cmd

    # Check environment
    assert env == {"ATMAN_DEMO_PACE": "off"}


def test_get_demo_command_with_repo_root() -> None:
    """Test get_demo_command with repo_root parameter."""
    repo_root = Path("/tmp/test-repo")
    cmd, env = get_demo_command("src/demo.py", paced=True, repo_root=repo_root)

    # Should not affect the output (parameter reserved for future use)
    assert isinstance(cmd, list)
    assert env == {"ATMAN_DEMO_PACE": "1"}
