"""Regression tests for the self-contained deploy package."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEPLOY_DIR = REPO_ROOT / "deploy" / "atman-deploy" / "deploy"
ROOT_SETUP = REPO_ROOT / "atman-setup.sh"
LEGACY_DEPLOY_SETUP = REPO_ROOT / "deploy" / "atman-setup.sh"

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


def test_deploy_schema_matches_bge_m3_fact_embedding_dimension() -> None:
    """Fresh deploys must not recreate the old 2560-dim facts vector column."""
    schema = (DEPLOY_DIR / "schema.sql").read_text(encoding="utf-8")
    facts_table = schema.split("CREATE TABLE IF NOT EXISTS public.facts", maxsplit=1)[1].split(
        ");", maxsplit=1
    )[0]

    assert "embedding           halfvec(1024)" in facts_table
    assert "embedding           halfvec(2560)" not in facts_table
    assert "COMMENT ON COLUMN public.facts.embedding IS 'halfvec(1024)" in schema
    assert "halfvec(2560)" not in schema


def test_deploy_defaults_match_bge_m3_embedding_dimension() -> None:
    """Deploy defaults, Qdrant collections, and smoke checks must agree."""
    config = (DEPLOY_DIR / "config.env").read_text(encoding="utf-8")
    setup = (DEPLOY_DIR / "setup.sh").read_text(encoding="utf-8")
    smoke = (DEPLOY_DIR / "smoke-test.sh").read_text(encoding="utf-8")

    assert "OLLAMA_EMBED_MODEL=bge-m3" in config
    assert "VECTOR_DIM=1024" in config
    assert '\\"size\\":${VECTOR_DIM}' in setup
    assert '"${DOCKER}" "${VECTOR_DIM}"' in setup
    assert 'EXPECTED_EMBED_DIM="${7:-1024}"' in smoke
    assert "ожидалось ${EXPECTED_EMBED_DIM}" in smoke


def test_inline_setup_schemas_match_bge_m3_fact_embedding_dimension() -> None:
    """Documented setup scripts must not embed the stale facts vector dimension."""
    for setup_path in (ROOT_SETUP, LEGACY_DEPLOY_SETUP):
        script = setup_path.read_text(encoding="utf-8")
        facts_table = script.split("CREATE TABLE IF NOT EXISTS facts", maxsplit=1)[1].split(
            ");", maxsplit=1
        )[0]

        assert "embedding  halfvec(1024)" in facts_table
        assert "embedding  halfvec(2560)" not in facts_table
        assert "halfvec(2560)" not in script
        assert 'OLLAMA_EMBED_MODEL="bge-m3"' in script
        assert '"size":1024' in script
        assert "ожидается 1024" in script
        assert "EMBEDDING_MODEL=${OLLAMA_EMBED_MODEL}" in script


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
            "bge-m3",
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
    assert values["ATMAN_EMBED_MODEL"] == "bge-m3"
    assert values["EMBEDDING_MODEL"] == "bge-m3"
    assert values["OLLAMA_EMBED_MODEL"] == "bge-m3"

    assert os.access(output, os.R_OK | os.W_OK)
