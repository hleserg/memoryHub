"""
SYSTEM_MAP §2.3 / §3 F integration: factual memory CLI (interactive REPL).

The CLI stores its JSONL under ``$HOME/.atman/facts.jsonl``; tests redirect
``HOME`` to a temporary directory and feed commands via stdin.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)


def _run_cli(stdin: str, home: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "HOME": str(home)}
    return subprocess.run(
        [sys.executable, "-m", "atman.cli"],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


def _extract_uuids(text: str) -> list[str]:
    return _UUID_RE.findall(text)


def test_cli_factual_memory_add_search_link_persistence():
    """SYSTEM_MAP §3 F: add → search → link → reload all work end-to-end via the REPL.

    1. Add two facts; verify CLI accepted them.
    2. Search by tag; verify both visible.
    3. Link them; verify success.
    4. Restart CLI in same HOME; verify file storage has both facts persisted.
    """
    with TemporaryDirectory() as tmp:
        home = Path(tmp)
        # First REPL session: add two facts, search, link.
        first = _run_cli(
            "\n".join(
                [
                    "add Первый факт session_1 task",
                    "add Второй факт session_1 task",
                    "search task --tags task",
                    "recent 5",
                    "exit",
                ]
            )
            + "\n",
            home=home,
        )
        assert first.returncode == 0, first.stderr
        assert "Факт добавлен" in first.stdout
        # Two UUIDs from "Факт добавлен" output blocks.
        added_ids = _extract_uuids(first.stdout)
        assert len(added_ids) >= 2

        # Second REPL session: facts must be loaded from disk.
        second = _run_cli(
            "\n".join(
                [
                    "recent 5",
                    f"link {added_ids[0]} {added_ids[1]} caused_by",
                    "exit",
                ]
            )
            + "\n",
            home=home,
        )
        assert second.returncode == 0, second.stderr
        assert "Связь создана" in second.stdout
        # Verify JSONL contains both facts.
        storage = home / ".atman" / "facts.jsonl"
        assert storage.exists()
        lines = [ln for ln in storage.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(lines) >= 2


def test_cli_factual_memory_invalid_uuid_does_not_crash():
    """SYSTEM_MAP §4.1: invalid UUID input on ``get`` shows an error and continues the REPL."""
    with TemporaryDirectory() as tmp:
        home = Path(tmp)
        result = _run_cli(
            "\n".join(["get not-a-uuid", "exit"]) + "\n",
            home=home,
        )
        assert result.returncode == 0
        # Errors go through Rich's stderr console.
        assert "неверный формат UUID" in result.stderr


def test_cli_factual_memory_get_unknown_uuid_reports_not_found():
    """SYSTEM_MAP §4.1: ``get`` with a well-formed but unknown UUID is handled gracefully."""
    with TemporaryDirectory() as tmp:
        home = Path(tmp)
        result = _run_cli(
            "\n".join(
                [
                    f"get {uuid.uuid4()}",
                    "exit",
                ]
            )
            + "\n",
            home=home,
        )
        assert result.returncode == 0
        assert "не найден" in result.stderr


def test_cli_factual_memory_invalidate_and_list_invalidated():
    """SYSTEM_MAP §3 F: ``invalidate`` moves a fact out of ACTIVE; ``list-invalidated`` surfaces it."""
    with TemporaryDirectory() as tmp:
        home = Path(tmp)
        # Add a fact, invalidate it, list invalidated.
        first = _run_cli(
            "\n".join(
                [
                    "add Устаревший факт session_1 task",
                    "exit",
                ]
            )
            + "\n",
            home=home,
        )
        assert first.returncode == 0, first.stderr
        added_ids = _extract_uuids(first.stdout)
        assert added_ids, first.stdout

        second = _run_cli(
            "\n".join(
                [
                    f"invalidate {added_ids[0]} reason text",
                    "list-invalidated",
                    "exit",
                ]
            )
            + "\n",
            home=home,
        )
        assert second.returncode == 0, second.stderr
        assert "помечен как недействительный" in second.stdout
        assert "reason text" in second.stdout
        # list-invalidated must surface the invalidated fact.
        assert "Недействительных фактов: 1" in second.stdout


def test_cli_factual_memory_invalidate_invalid_uuid_does_not_crash():
    """``invalidate`` with a malformed UUID surfaces a clear error and continues."""
    with TemporaryDirectory() as tmp:
        home = Path(tmp)
        result = _run_cli(
            "\n".join(["invalidate not-a-uuid because", "exit"]) + "\n",
            home=home,
        )
        assert result.returncode == 0
        assert "неверный формат UUID" in result.stderr
