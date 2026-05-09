"""Regression tests for the self-contained deploy package."""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEPLOY_DIR = REPO_ROOT / "deploy" / "atman-deploy" / "deploy"
DEPLOY_ZIP = REPO_ROOT / "deploy" / "atman-deploy.zip"

REQUIRED_RUNTIME_FILES = {
    ".gitignore",
    "Makefile",
    "README.md",
    "config.env",
    "docker-compose.yml.tpl",
    "gen-secrets.sh",
    "install-docker.sh",
    "ollama-override.conf.tpl",
    "schema.sql",
    "setup.sh",
    "smoke-test.sh",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_deploy_directory_contains_all_runtime_files() -> None:
    """The checked-out deploy tree must include every file setup.sh calls."""
    missing = sorted(name for name in REQUIRED_RUNTIME_FILES if not (DEPLOY_DIR / name).exists())

    assert missing == []


def test_deploy_runtime_files_are_not_gitignored() -> None:
    """Required scripts must not disappear again because of broad ignore rules."""
    candidates = [str(DEPLOY_DIR / name) for name in sorted(REQUIRED_RUNTIME_FILES)]
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", "--", *candidates],
        cwd=REPO_ROOT,
        check=False,
    )

    assert result.returncode == 1


def test_deploy_zip_matches_checked_out_runtime_files() -> None:
    """The zip artifact is the user-facing distribution and must stay in sync."""
    with zipfile.ZipFile(DEPLOY_ZIP) as archive:
        names = set(archive.namelist())
        for name in REQUIRED_RUNTIME_FILES:
            archive_name = f"deploy/{name}"
            assert archive_name in names
            assert hashlib.sha256(archive.read(archive_name)).hexdigest() == _sha256(
                DEPLOY_DIR / name
            )


def test_gen_secrets_writes_restricted_env_file(tmp_path: Path) -> None:
    output = tmp_path / ".atman" / ".secrets"
    result = subprocess.run(
        [
            "bash",
            str(DEPLOY_DIR / "gen-secrets.sh"),
            str(output),
            "atman",
            "atman",
            "5432",
            "6333",
            "qwen3:14b",
            "qwen3-embedding:1.5b",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert stat.S_IMODE(output.stat().st_mode) == 0o600

    values = dict(
        line.split("=", maxsplit=1)
        for line in output.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )
    assert values["POSTGRES_USER"] == "atman"
    assert values["POSTGRES_DB"] == "atman"
    assert values["POSTGRES_PORT"] == "5432"
    assert values["DATABASE_URL"].startswith("postgresql://atman:")
    assert values["QDRANT_URL"] == "http://localhost:6333"
    assert len(values["POSTGRES_PASSWORD"]) == 32
    assert len(values["QDRANT_API_KEY"]) == 32
    assert values["ATMAN_OLLAMA_MODEL"] == "qwen3:14b"
    assert values["ATMAN_EMBED_MODEL"] == "qwen3-embedding:1.5b"

    assert os.access(output, os.R_OK | os.W_OK)
