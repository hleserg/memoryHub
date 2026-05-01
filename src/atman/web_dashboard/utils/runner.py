"""Process runner utilities for web dashboard."""

from __future__ import annotations

import asyncio
import subprocess
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

    process = await asyncio.create_subprocess_exec(
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
) -> tuple[int, str]:
    """
    Run command synchronously and capture output.

    Args:
        args: Command arguments
        cwd: Working directory
        env: Environment variables to add/override

    Returns:
        Tuple of (exit_code, output)
    """
    import os

    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    result = subprocess.run(
        args,
        cwd=str(cwd),
        env=merged_env,
        capture_output=True,
        text=True,
    )

    return result.returncode, result.stdout + result.stderr
