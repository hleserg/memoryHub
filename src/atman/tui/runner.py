"""Async subprocess runner with streaming stdout (stderr merged)."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Mapping
from pathlib import Path


async def stream_command(
    argv: list[str],
    cwd: Path,
    *,
    env: Mapping[str, str] | None = None,
    on_line: Callable[[str], None] | None = None,
) -> int:
    """Run ``argv`` with ``cwd``, stream stdout+stderr line-by-line to ``on_line``.

    Returns the process exit code.
    """
    merged = os.environ.copy()
    if env:
        merged.update(dict(env))
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=merged,
    )
    if proc.stdout is None:
        code = await proc.wait()
        return int(code or 0)

    buf = b""
    while True:
        chunk = await proc.stdout.read(4096)
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            raw_line, buf = buf.split(b"\n", 1)
            line = raw_line.decode("utf-8", errors="replace") + "\n"
            if on_line:
                on_line(line)
    if buf and on_line:
        on_line(buf.decode("utf-8", errors="replace"))

    code = await proc.wait()
    return int(code or 0)
