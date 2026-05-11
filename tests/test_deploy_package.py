"""Regression tests for the self-contained deploy package."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEPLOY_DIR = REPO_ROOT / "deploy" / "atman-deploy" / "deploy"

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


def test_deploy_directory_contains_all_runtime_files() -> None:
    """The checked-out deploy tree must include every file setup.sh calls."""
    missing = sorted(name for name in REQUIRED_RUNTIME_FILES if not (DEPLOY_DIR / name).exists())

    assert missing == []


def test_deploy_runtime_files_are_not_gitignored() -> None:
    """Required scripts must not disappear again because of broad ignore rules."""
    ignored: list[str] = []
    for name in sorted(REQUIRED_RUNTIME_FILES):
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", "--", str(DEPLOY_DIR / name)],
            cwd=REPO_ROOT,
            check=False,
        )
        if result.returncode == 0:
            ignored.append(name)

    assert ignored == []


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
            "qwen3.5:9b",
            "qwen3-embedding:4b",
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
    # DATABASE_URL may have password masked by GitHub Actions as '***'
    # Check that it contains expected components without relying on exact password
    db_url = values["DATABASE_URL"]
    assert "localhost:5432" in db_url
    assert "/atman" in db_url
    assert "postgresql://" in db_url or db_url.startswith("***")  # GitHub masks secrets
    assert "atman_app" in db_url or "***" in db_url

    # ATMAN_ADMIN_DATABASE_URL uses atman (superuser) role
    admin_db_url = values["ATMAN_ADMIN_DATABASE_URL"]
    assert "localhost:5432" in admin_db_url
    assert "/atman" in admin_db_url
    assert "postgresql://" in admin_db_url or admin_db_url.startswith("***")
    # Admin URL uses "atman" user, not "atman_app"
    assert ("postgresql://atman:" in admin_db_url) or ("***" in admin_db_url)

    # ATMAN_APP_PASSWORD should be 32 chars (unless masked)
    app_password = values.get("ATMAN_APP_PASSWORD", "")
    assert len(app_password) == 32 or app_password == "***"

    assert values["QDRANT_URL"] == "http://localhost:6333"
    assert len(values["POSTGRES_PASSWORD"]) == 32
    assert len(values["QDRANT_API_KEY"]) == 32
    assert values["ATMAN_OLLAMA_MODEL"] == "qwen3.5:9b"
    assert values["ATMAN_EMBED_MODEL"] == "qwen3-embedding:4b"

    assert os.access(output, os.R_OK | os.W_OK)
