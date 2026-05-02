"""Tests for web_dashboard.utils.runner module."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from atman.web_dashboard.utils.runner import run_command_async, run_command_sync


@pytest.mark.asyncio
async def test_run_command_async_success() -> None:
    """Test run_command_async with successful command."""
    test_output = "test output\n"

    mock_process = AsyncMock()
    mock_process.wait = AsyncMock(return_value=0)
    mock_process.stdout = AsyncMock()
    mock_process.stdout.__aiter__.return_value = [test_output.encode()]

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        exit_code, output = await run_command_async(["echo", "test"], Path("/tmp"))

    assert exit_code == 0
    assert output == test_output


@pytest.mark.asyncio
async def test_run_command_async_with_callback() -> None:
    """Test run_command_async with line callback."""
    lines_received: list[str] = []

    def on_line(line: str) -> None:
        lines_received.append(line)

    mock_process = AsyncMock()
    mock_process.wait = AsyncMock(return_value=0)
    mock_process.stdout = AsyncMock()
    mock_process.stdout.__aiter__.return_value = [
        b"line1\n",
        b"line2\n",
    ]

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        exit_code, output = await run_command_async(["echo", "test"], Path("/tmp"), on_line=on_line)

    assert exit_code == 0
    assert len(lines_received) == 2
    assert lines_received[0] == "line1\n"
    assert lines_received[1] == "line2\n"


@pytest.mark.asyncio
async def test_run_command_async_with_env() -> None:
    """Test run_command_async with custom environment."""
    mock_process = AsyncMock()
    mock_process.wait = AsyncMock(return_value=0)
    mock_process.stdout = AsyncMock()
    mock_process.stdout.__aiter__.return_value = []

    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        await run_command_async(["test"], Path("/tmp"), env={"TEST_VAR": "value"})

        # Check that env was merged
        call_kwargs = mock_exec.call_args[1]
        assert "TEST_VAR" in call_kwargs["env"]
        assert call_kwargs["env"]["TEST_VAR"] == "value"


@pytest.mark.asyncio
async def test_run_command_async_failure() -> None:
    """Test run_command_async with failing command."""
    mock_process = AsyncMock()
    mock_process.wait = AsyncMock(return_value=1)
    mock_process.stdout = AsyncMock()
    mock_process.stdout.__aiter__.return_value = [b"error\n"]

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        exit_code, output = await run_command_async(["false"], Path("/tmp"))

    assert exit_code == 1
    assert output == "error\n"


def test_run_command_sync_success() -> None:
    """Test run_command_sync with successful command."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "stdout output"
    mock_result.stderr = "stderr output"

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        exit_code, output = run_command_sync(["echo", "test"], Path("/tmp"))

        # Check that timeout was passed
        assert mock_run.call_args[1]["timeout"] == 300

    assert exit_code == 0
    assert output == "stdout outputstderr output"


def test_run_command_sync_with_env() -> None:
    """Test run_command_sync with custom environment."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = ""
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        run_command_sync(["test"], Path("/tmp"), env={"TEST_VAR": "value"})

        # Check that env was passed
        call_kwargs = mock_run.call_args[1]
        assert "TEST_VAR" in call_kwargs["env"]
        assert call_kwargs["env"]["TEST_VAR"] == "value"


def test_run_command_sync_failure() -> None:
    """Test run_command_sync with failing command."""
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = "stdout"
    mock_result.stderr = "error"

    with patch("subprocess.run", return_value=mock_result):
        exit_code, output = run_command_sync(["false"], Path("/tmp"))

    assert exit_code == 1
    assert output == "stdouterror"


def test_run_command_sync_cwd() -> None:
    """Test run_command_sync uses correct working directory."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = ""
    mock_result.stderr = ""

    test_path = Path("/test/path")

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        run_command_sync(["test"], test_path)

        # Check that cwd was passed as string
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["cwd"] == str(test_path)


def test_run_command_sync_timeout() -> None:
    """Test run_command_sync handles timeout correctly."""
    mock_timeout = subprocess.TimeoutExpired(["test"], 300)
    mock_timeout.stdout = b"partial output"
    mock_timeout.stderr = b"error output"

    with patch("subprocess.run", side_effect=mock_timeout):
        exit_code, output = run_command_sync(["slow-command"], Path("/tmp"))

    assert exit_code == 124  # Standard timeout exit code
    assert "partial output" in output
    assert "error output" in output
    assert "timed out after 300 seconds" in output


def test_run_command_sync_custom_timeout() -> None:
    """Test run_command_sync with custom timeout."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = ""
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        run_command_sync(["test"], Path("/tmp"), timeout=60)

        # Check that custom timeout was passed
        assert mock_run.call_args[1]["timeout"] == 60
