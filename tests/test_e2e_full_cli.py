"""
P2.8 — Full end-to-end CLI test: subprocess from first command to final file.

Single test exercises the complete user journey in one temp workspace:
  1. identity init
  2. experience add
  3. reflect micro  (via --fixtures, since workspace-based reflection is pending)
  4. identity snapshot
  5. narrative render
  6. narrative validate
  7. Verify all expected files exist and have correct structure

This is the closest equivalent to "run the whole system from scratch" — it
catches integration failures that only surface when all components are wired
together through the real CLI entry points.

SYSTEM_MAP §3 A–G end-to-end / §5.3 regression freeze.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

AGENT_ID = "00000000-0000-4000-8000-000000000077"


def _run(module: str, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=cwd,
    )


@pytest.mark.slow
@pytest.mark.e2e
def test_full_cli_lifecycle(tmp_path: Path) -> None:
    """SYSTEM_MAP §3 A–G: complete CLI lifecycle in a single workspace."""
    ws = tmp_path / "workspace"
    ws.mkdir()

    # ---- A. identity init --------------------------------------------------
    r = _run("atman.cli_identity", "init", "--workspace", str(ws), "--agent-id", AGENT_ID)
    assert r.returncode == 0, f"identity init failed:\n{r.stderr}"
    assert "Created identity" in r.stdout

    identity_file = ws / "identity.json"
    assert identity_file.exists()
    identity_data = json.loads(identity_file.read_text(encoding="utf-8"))
    assert identity_data["id"] == AGENT_ID

    # ---- B. identity show --------------------------------------------------
    r = _run("atman.cli_identity", "show", "--workspace", str(ws), "--agent-id", AGENT_ID)
    assert r.returncode == 0, f"identity show failed:\n{r.stderr}"
    assert AGENT_ID in r.stdout

    # ---- C. experience add -------------------------------------------------
    fixture = tmp_path / "experience.json"
    fixture.write_text(
        json.dumps(
            {
                "session_id": str(uuid4()),
                "timestamp": "2025-06-01T10:00:00+00:00",
                "key_moments": [
                    {
                        "what_happened": "full e2e CLI test experience",
                        "how_i_felt": {
                            "emotional_valence": 0.6,
                            "emotional_intensity": 0.7,
                            "depth": "profound",
                        },
                        "why_it_matters": "e2e coverage",
                        "values_touched": ["honesty", "competence"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    import os

    home = tmp_path / "home"
    home.mkdir()
    env = {**os.environ, "HOME": str(home)}
    r = subprocess.run(
        [sys.executable, "-m", "atman.cli_experience"],
        input=f"experience add {fixture}\nexit\n",
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    assert r.returncode == 0, f"experience add failed:\n{r.stderr}"
    assert "Experience created" in r.stdout

    experiences_file = home / ".atman" / "experiences.jsonl"
    assert experiences_file.exists()
    lines = [ln for ln in experiences_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1

    # ---- D. reflect micro (fixture-based) ----------------------------------
    r = _run("atman.cli_reflection", "reflect", "micro", "--fixtures")
    assert r.returncode == 0, f"reflect micro failed:\n{r.stderr}"

    # ---- E. identity snapshot ----------------------------------------------
    r = _run(
        "atman.cli_identity",
        "snapshot",
        "--workspace",
        str(ws),
        "--agent-id",
        AGENT_ID,
        "--description",
        "e2e lifecycle snapshot",
    )
    assert r.returncode == 0, f"identity snapshot failed:\n{r.stderr}"
    assert "Created snapshot" in r.stdout

    snapshots = list((ws / "identity_snapshots").glob("*.json"))
    assert len(snapshots) >= 1
    descriptions = [json.loads(f.read_text(encoding="utf-8"))["description"] for f in snapshots]
    assert "e2e lifecycle snapshot" in descriptions

    # ---- F. narrative render -----------------------------------------------
    r = _run(
        "atman.cli_identity",
        "render",
        "--workspace",
        str(ws),
        "--agent-id",
        AGENT_ID,
    )
    assert r.returncode == 0, f"narrative render failed:\n{r.stderr}"

    narrative_file = ws / "NARRATIVE.md"
    assert narrative_file.exists()
    content = narrative_file.read_text(encoding="utf-8")
    assert "# NARRATIVE" in content
    assert "## CORE LAYER" in content
    assert "## RECENT LAYER" in content

    # ---- G. narrative validate ---------------------------------------------
    r = _run("atman.cli_identity", "validate", str(narrative_file))
    assert r.returncode == 0, f"narrative validate failed:\n{r.stderr}"
    assert "valid" in r.stdout.lower()
