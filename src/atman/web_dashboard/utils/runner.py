"""Process runner utilities for web dashboard."""

from __future__ import annotations

import asyncio
import subprocess  # nosec B404
from collections.abc import Callable
from pathlib import Path


async def run_command_async(
    args: list[str],
    cwd: Path,
    env: dict[str, str] | None = None,
    on_line: Callable[[str], None] | None = None,
) -> tuple[int, str]:
    """
    Run command asynchronously and stream output.

    Args:
        args: Command arguments
        cwd: Working directory
        env: Environment variables to add/override
        on_line: Optional callback for each output line

    Returns:
        Tuple of (exit_code, full_output)
    """
    import os

    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    process = await asyncio.create_subprocess_exec(  # nosec B603
        *args,
        cwd=str(cwd),
        env=merged_env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    output_lines: list[str] = []

    if process.stdout:
        async for line_bytes in process.stdout:
            line = line_bytes.decode("utf-8", errors="replace")
            output_lines.append(line)
            if on_line:
                on_line(line)

    exit_code = await process.wait()
    full_output = "".join(output_lines)

    return exit_code, full_output


def run_command_sync(
    args: list[str],
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: int = 300,
) -> tuple[int, str]:
    """
    Run command synchronously and capture output.

    Args:
        args: Command arguments
        cwd: Working directory
        env: Environment variables to add/override
        timeout: Timeout in seconds (default: 300s / 5 minutes)

    Returns:
        Tuple of (exit_code, output)
    """
    import os

    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    try:
        result = subprocess.run(  # nosec B603
            args,
            cwd=str(cwd),
            env=merged_env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout + result.stderr
    except subprocess.TimeoutExpired as e:
        output = ""
        if e.stdout:
            output += (
                e.stdout.decode("utf-8", errors="replace")
                if isinstance(e.stdout, bytes)
                else e.stdout
            )
        if e.stderr:
            output += (
                e.stderr.decode("utf-8", errors="replace")
                if isinstance(e.stderr, bytes)
                else e.stderr
            )
        output += f"\n\n❌ Command timed out after {timeout} seconds"
        return 124, output  # Standard timeout exit code
