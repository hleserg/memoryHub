"""
P0.3 — CLI → file → CLI round-trip tests.

Each test runs a sequence of CLI subcommands via subprocess, verifying that:
1. The command exits with code 0 and produces expected stdout.
2. The expected files are created on disk with correct structure.
3. A subsequent CLI read command retrieves the persisted data correctly.

This guards against agents breaking the CLI↔storage contract (e.g., changing
file paths, serialization format, or CLI argument parsing).

SYSTEM_MAP §3 A–B / §4.1 / §5.3 regression freeze.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4


def _run(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", *args],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=cwd,
    )


AGENT_ID = "00000000-0000-4000-8000-000000000099"


# ---------------------------------------------------------------------------
# identity init → file created → identity show reads it back
# ---------------------------------------------------------------------------


def test_identity_init_creates_file_and_show_reads_it(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()

    # Step 1: init
    r = _run(["atman.cli_identity", "init", "--workspace", str(ws), "--agent-id", AGENT_ID])
    assert r.returncode == 0, r.stderr
    assert "Created identity" in r.stdout

    # Step 2: verify file on disk
    identity_file = ws / "identity.json"
    assert identity_file.exists(), "identity.json must be created by init"
    data = json.loads(identity_file.read_text(encoding="utf-8"))
    assert data["id"] == AGENT_ID

    # Step 3: show reads back from same file
    r2 = _run(["atman.cli_identity", "show", "--workspace", str(ws), "--agent-id", AGENT_ID])
    assert r2.returncode == 0, r2.stderr
    assert AGENT_ID in r2.stdout


def test_identity_init_double_init_fails(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()

    _run(["atman.cli_identity", "init", "--workspace", str(ws), "--agent-id", AGENT_ID])
    r2 = _run(["atman.cli_identity", "init", "--workspace", str(ws), "--agent-id", AGENT_ID])
    assert r2.returncode == 1
    assert "already exists" in r2.stderr


def test_identity_show_unknown_agent_fails(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()

    r = _run(["atman.cli_identity", "show", "--workspace", str(ws), "--agent-id", AGENT_ID])
    assert r.returncode == 1
    assert "not found" in r.stderr


def test_identity_snapshot_creates_snapshot_file(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()

    _run(["atman.cli_identity", "init", "--workspace", str(ws), "--agent-id", AGENT_ID])

    r = _run(
        [
            "atman.cli_identity",
            "snapshot",
            "--workspace",
            str(ws),
            "--agent-id",
            AGENT_ID,
            "--description",
            "round-trip snapshot",
        ]
    )
    assert r.returncode == 0, r.stderr
    assert "Created snapshot" in r.stdout

    snapshots_dir = ws / "identity_snapshots"
    snap_files = list(snapshots_dir.glob("*.json"))
    assert len(snap_files) >= 1
    descriptions = [json.loads(f.read_text(encoding="utf-8"))["description"] for f in snap_files]
    assert "round-trip snapshot" in descriptions


def test_narrative_render_creates_markdown_file(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()

    _run(["atman.cli_identity", "init", "--workspace", str(ws), "--agent-id", AGENT_ID])

    r = _run(
        [
            "atman.cli_identity",
            "render",
            "--workspace",
            str(ws),
            "--agent-id",
            AGENT_ID,
        ]
    )
    assert r.returncode == 0, r.stderr
    assert "Rendered narrative" in r.stdout

    narrative_file = ws / "NARRATIVE.md"
    assert narrative_file.exists(), "NARRATIVE.md must be created by render"
    content = narrative_file.read_text(encoding="utf-8")
    assert "# NARRATIVE" in content
    assert "## CORE LAYER" in content


def test_narrative_validate_accepts_rendered_file(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()

    _run(["atman.cli_identity", "init", "--workspace", str(ws), "--agent-id", AGENT_ID])
    _run(
        [
            "atman.cli_identity",
            "render",
            "--workspace",
            str(ws),
            "--agent-id",
            AGENT_ID,
        ]
    )

    narrative_file = ws / "NARRATIVE.md"
    r = _run(["atman.cli_identity", "validate", str(narrative_file)])
    assert r.returncode == 0, r.stderr
    assert "valid" in r.stdout.lower()


# ---------------------------------------------------------------------------
# experience add → file created → experience search finds it
# ---------------------------------------------------------------------------


def test_experience_add_creates_file_and_search_finds_it(tmp_path: Path) -> None:
    import os

    fixture = tmp_path / "exp.json"
    fixture.write_text(
        json.dumps(
            {
                "session_id": str(uuid4()),
                "timestamp": "2025-06-01T10:00:00+00:00",
                "key_moments": [
                    {
                        "what_happened": "CLI round-trip test",
                        "how_i_felt": {
                            "emotional_valence": 0.5,
                            "emotional_intensity": 0.6,
                            "depth": "meaningful",
                        },
                        "why_it_matters": "coverage",
                        "values_touched": ["honesty"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    env = {**os.environ, "HOME": str(tmp_path)}

    r_add = subprocess.run(
        [sys.executable, "-m", "atman.cli_experience"],
        input="experience add " + str(fixture) + "\nexit\n",
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    assert r_add.returncode == 0, r_add.stderr
    assert "Experience created" in r_add.stdout
    import re

    match = re.search(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        r_add.stdout,
        re.IGNORECASE,
    )
    assert match, f"No experience UUID in add output: {r_add.stdout}"
    exp_id = match.group(0)

    storage = tmp_path / ".atman" / "experiences.jsonl"
    assert storage.exists(), "experiences.jsonl must exist after add"
    lines = [ln for ln in storage.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1

    r_search = subprocess.run(
        [sys.executable, "-m", "atman.cli_experience"],
        input="experience search values honesty\nexit\n",
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    assert r_search.returncode == 0, r_search.stderr
    assert "Found" in r_search.stdout
    assert exp_id in r_search.stdout


# ---------------------------------------------------------------------------
# CLI commands without initialized workspace return clean errors
# ---------------------------------------------------------------------------


def test_identity_show_missing_workspace_exits_nonzero(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    r = _run(["atman.cli_identity", "show", "--workspace", str(empty), "--agent-id", AGENT_ID])
    assert r.returncode != 0
    assert "not found" in r.stderr


def test_identity_snapshot_missing_workspace_exits_nonzero(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    r = _run(
        [
            "atman.cli_identity",
            "snapshot",
            "--workspace",
            str(empty),
            "--agent-id",
            AGENT_ID,
            "--description",
            "x",
        ]
    )
    assert r.returncode != 0
    assert "not found" in r.stderr
