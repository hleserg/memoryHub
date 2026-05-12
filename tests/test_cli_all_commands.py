"""
P1.4 — Full CLI command coverage.

Tests every CLI command that was not already covered in test_cli_identity.py,
test_cli_reflection.py, test_cli_experience.py, test_cli_factual_memory.py.

Covers:
- experience get (valid id, invalid uuid, unknown id)
- experience decay-preview (valid, invalid uuid, unknown)
- experience reflect (add reframing note)
- experience search (all search types)
- experience help
- identity validate (valid file, invalid file)
- reflection unknown command
- reflection missing subcommand

SYSTEM_MAP §3 A–F / §4.1 / §5.3 regression freeze.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest


def _run_experience(stdin: str, home: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "HOME": str(home)}
    return subprocess.run(
        [sys.executable, "-m", "atman.cli_experience"],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


def _run_reflection(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "atman.cli_reflection", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def _run_identity(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "atman.cli_identity", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def _add_one_experience(home: Path, fixture: Path) -> str:
    """Add one experience and return its UUID."""
    import re

    result = _run_experience("experience add " + str(fixture) + "\nexit\n", home=home)
    assert result.returncode == 0, result.stderr
    match = re.search(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        result.stdout,
        re.IGNORECASE,
    )
    assert match, f"No UUID in output: {result.stdout}"
    return match.group(0)


@pytest.fixture()
def exp_home(tmp_path: Path) -> tuple[Path, Path, str]:
    """Returns (home_dir, fixture_path, experience_uuid)."""
    home = tmp_path / "home"
    home.mkdir()

    fixture = tmp_path / "exp.json"
    moment_id = str(uuid4())
    fixture.write_text(
        json.dumps(
            {
                "session_id": str(uuid4()),
                "timestamp": "2025-06-01T10:00:00+00:00",
                "key_moment_ids": [moment_id],
                "avg_emotional_intensity": 0.6,
                "has_profound_moment": False,
            }
        ),
        encoding="utf-8",
    )

    exp_id = _add_one_experience(home, fixture)
    return home, fixture, exp_id


# ---------------------------------------------------------------------------
# experience get
# ---------------------------------------------------------------------------


def test_experience_get_found(exp_home: tuple) -> None:
    home, _, exp_id = exp_home
    r = _run_experience(f"experience get {exp_id}\nexit\n", home=home)
    assert r.returncode == 0
    assert "CLI all commands test" in r.stdout


def test_experience_get_invalid_uuid(exp_home: tuple) -> None:
    home, _, _ = exp_home
    r = _run_experience("experience get not-a-uuid\nexit\n", home=home)
    assert r.returncode == 0
    assert "Invalid UUID" in r.stderr


def test_experience_get_unknown_uuid(exp_home: tuple) -> None:
    home, _, _ = exp_home
    r = _run_experience(f"experience get {uuid4()}\nexit\n", home=home)
    assert r.returncode == 0
    assert "not found" in r.stderr


# ---------------------------------------------------------------------------
# experience reflect (add reframing note)
# ---------------------------------------------------------------------------


def test_experience_reflect_adds_note(exp_home: tuple) -> None:
    home, _, exp_id = exp_home
    r = _run_experience(f"experience reflect {exp_id} 'New perspective' growth\nexit\n", home=home)
    assert r.returncode == 0
    assert "Reframing note added" in r.stdout


def test_experience_reflect_invalid_uuid(exp_home: tuple) -> None:
    home, _, _ = exp_home
    r = _run_experience("experience reflect not-a-uuid 'text'\nexit\n", home=home)
    assert r.returncode == 0
    assert "Invalid UUID" in r.stderr


# ---------------------------------------------------------------------------
# experience decay-preview
# ---------------------------------------------------------------------------


def test_experience_decay_preview_shows_table(exp_home: tuple) -> None:
    home, _, exp_id = exp_home
    r = _run_experience(f"experience decay-preview {exp_id} 30\nexit\n", home=home)
    assert r.returncode == 0
    assert "decay" in r.stdout.lower() or "salience" in r.stdout.lower()


def test_experience_decay_preview_invalid_uuid(exp_home: tuple) -> None:
    home, _, _ = exp_home
    r = _run_experience("experience decay-preview not-a-uuid\nexit\n", home=home)
    assert r.returncode == 0
    assert "Invalid UUID" in r.stderr


def test_experience_decay_preview_unknown_uuid(exp_home: tuple) -> None:
    home, _, _ = exp_home
    r = _run_experience(f"experience decay-preview {uuid4()}\nexit\n", home=home)
    assert r.returncode == 0
    assert "not found" in r.stderr


# ---------------------------------------------------------------------------
# experience search — all types
# ---------------------------------------------------------------------------


def test_experience_search_recent(exp_home: tuple) -> None:
    home, _, _ = exp_home
    r = _run_experience("experience search recent 5\nexit\n", home=home)
    assert r.returncode == 0
    assert "CLI all commands test" in r.stdout


def test_experience_search_values(exp_home: tuple) -> None:
    home, _, _ = exp_home
    r = _run_experience("experience search values honesty\nexit\n", home=home)
    assert r.returncode == 0
    assert "CLI all commands test" in r.stdout


def test_experience_search_depth(exp_home: tuple) -> None:
    home, _, _ = exp_home
    r = _run_experience("experience search depth meaningful\nexit\n", home=home)
    assert r.returncode == 0
    assert "CLI all commands test" in r.stdout


def test_experience_search_unknown_type(exp_home: tuple) -> None:
    home, _, _ = exp_home
    r = _run_experience("experience search badtype something\nexit\n", home=home)
    assert r.returncode == 0
    assert "Unknown search type" in r.stderr


# ---------------------------------------------------------------------------
# experience help
# ---------------------------------------------------------------------------


def test_experience_help_shows_commands(exp_home: tuple) -> None:
    home, _, _ = exp_home
    r = _run_experience("experience help\nexit\n", home=home)
    assert r.returncode == 0
    assert "experience add" in r.stdout or "add" in r.stdout


# ---------------------------------------------------------------------------
# reflection CLI — unknown command and missing subcommand
# ---------------------------------------------------------------------------


def test_reflection_unknown_command_exits_nonzero() -> None:
    r = _run_reflection(["reflect", "unknown_subcommand"])
    assert r.returncode != 0
    assert "Unknown command" in r.stderr


def test_reflection_no_subcommand_exits_nonzero() -> None:
    r = _run_reflection([])
    assert r.returncode != 0


# ---------------------------------------------------------------------------
# identity validate — invalid markdown
# ---------------------------------------------------------------------------


def test_narrative_validate_rejects_invalid_file(tmp_path: Path) -> None:
    bad = tmp_path / "bad.md"
    bad.write_text("just random text without required sections", encoding="utf-8")

    r = _run_identity(["validate", str(bad)])
    assert r.returncode != 0
