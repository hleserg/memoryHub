"""HLE-38 — install-external installer tests."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Mapping
from pathlib import Path
from uuid import uuid4

import pytest

from atman.skills.in_memory_store import InMemorySkillStore
from atman.skills.installer import (
    SkillInstallError,
    install_external,
)
from atman.skills.manifest import SkillManifest, write_skill_md
from atman.skills.models import SkillKind, SkillOrigin, SkillStatus


def _write_manifest(root: Path, *, name: str = "demo", runtime_entry: str | None = None) -> None:
    root.mkdir(parents=True, exist_ok=True)
    write_skill_md(
        SkillManifest(
            name=name,
            description=f"{name} demo skill",
            kind=SkillKind.active,
            origin=SkillOrigin.external,
            runtime_entry=runtime_entry,
            runtime_sandbox="subprocess" if runtime_entry else "none",
            body=f"# {name}\n\nDoes things.",
        ),
        root / "SKILL.md",
    )


def _make_zip(payload: Mapping[str, str | bytes]) -> bytes:
    """Build a zip in memory from a {arcname: contents} mapping."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for arcname, content in payload.items():
            if isinstance(content, str):
                zf.writestr(arcname, content)
            else:
                zf.writestr(arcname, content)
    return buf.getvalue()


# ── local directory source ────────────────────────────────────────────────


def test_install_local_directory_writes_skill_row(tmp_path: Path) -> None:
    src = tmp_path / "src"
    _write_manifest(src, name="demo")
    store = InMemorySkillStore()
    agent_id = uuid4()
    agents_root = tmp_path / "agents"

    result = install_external(str(src), agent_id, store=store, agents_root=agents_root)

    assert result.dry_run is False
    assert result.skill_id is not None
    assert result.target_path == agents_root / str(agent_id) / "skills" / "demo"
    assert result.target_path.exists()
    assert (result.target_path / "SKILL.md").exists()

    # Store row exists and is active + external
    stored = store.get_skill_by_name(agent_id, "demo")
    assert stored is not None
    assert stored.status == SkillStatus.active
    assert stored.origin == SkillOrigin.external


def test_install_dry_run_writes_nothing(tmp_path: Path) -> None:
    src = tmp_path / "src"
    _write_manifest(src, name="demo")
    store = InMemorySkillStore()
    agent_id = uuid4()
    agents_root = tmp_path / "agents"

    result = install_external(
        str(src), agent_id, store=store, agents_root=agents_root, dry_run=True
    )

    assert result.dry_run is True
    assert result.skill_id is None
    assert not (agents_root / str(agent_id) / "skills" / "demo").exists()
    assert store.get_skill_by_name(agent_id, "demo") is None


def test_install_rejects_missing_manifest(tmp_path: Path) -> None:
    src = tmp_path / "empty"
    src.mkdir()
    store = InMemorySkillStore()

    with pytest.raises(SkillInstallError, match=r"No SKILL\.md"):
        install_external(str(src), uuid4(), store=store, agents_root=tmp_path / "agents")


def test_install_rejects_duplicate_target(tmp_path: Path) -> None:
    src = tmp_path / "src"
    _write_manifest(src, name="demo")
    store = InMemorySkillStore()
    agent_id = uuid4()
    agents_root = tmp_path / "agents"

    install_external(str(src), agent_id, store=store, agents_root=agents_root)

    # Second install with same name fails before clobbering
    with pytest.raises(SkillInstallError, match="already exists"):
        install_external(str(src), agent_id, store=store, agents_root=agents_root)


def test_install_rejects_duplicate_name_in_store(tmp_path: Path) -> None:
    """Pre-existing store row blocks install even when target dir is absent."""
    src = tmp_path / "src"
    _write_manifest(src, name="demo")
    agent_id = uuid4()
    store = InMemorySkillStore()
    # Insert a fake skill with the same name but a different on-disk path
    from datetime import UTC, datetime

    from atman.skills.models import Skill

    now = datetime.now(UTC)
    store.save_skill(
        Skill(
            id=uuid4(),
            agent_id=agent_id,
            entity_id=uuid4(),
            name="demo",
            description="x",
            version="0.1.0",
            kind=SkillKind.active,
            status=SkillStatus.active,
            origin=SkillOrigin.in_session,
            core=False,
            session_scoped=False,
            user_pinned=False,
            auto_pinned=False,
            invocations_count=0,
            success_count=0,
            failure_count=0,
            last_used_at=None,
            sessions_since_use=0,
            revision_needed=False,
            revision_priority=0,
            last_revised_at=None,
            manifest_inferred=False,
            skill_root=tmp_path / "old",
            manifest_path=tmp_path / "old/SKILL.md",
            created_at=now,
            updated_at=now,
        )
    )
    with pytest.raises(SkillInstallError, match="already registered"):
        install_external(str(src), agent_id, store=store, agents_root=tmp_path / "agents")


def test_name_override_applied(tmp_path: Path) -> None:
    src = tmp_path / "src"
    _write_manifest(src, name="demo")
    store = InMemorySkillStore()
    agent_id = uuid4()
    agents_root = tmp_path / "agents"

    result = install_external(
        str(src),
        agent_id,
        store=store,
        agents_root=agents_root,
        name_override="custom-name",
    )

    assert result.manifest.name == "custom-name"
    assert (agents_root / str(agent_id) / "skills" / "custom-name" / "SKILL.md").exists()
    assert store.get_skill_by_name(agent_id, "custom-name") is not None
    assert store.get_skill_by_name(agent_id, "demo") is None


def test_invalid_name_override_rejected(tmp_path: Path) -> None:
    src = tmp_path / "src"
    _write_manifest(src, name="demo")
    store = InMemorySkillStore()

    with pytest.raises(SkillInstallError, match="kebab-case alphanumeric"):
        install_external(
            str(src),
            uuid4(),
            store=store,
            agents_root=tmp_path / "agents",
            name_override="has spaces!",
        )


def test_runtime_entry_sets_warning_flag(tmp_path: Path) -> None:
    src = tmp_path / "src"
    _write_manifest(src, name="demo", runtime_entry="scripts/run.py")
    (src / "scripts").mkdir()
    (src / "scripts" / "run.py").write_text("print('hi')\n")

    store = InMemorySkillStore()
    result = install_external(
        str(src),
        uuid4(),
        store=store,
        agents_root=tmp_path / "agents",
        dry_run=True,
    )
    assert result.runtime_warning is True


# ── zip handling ──────────────────────────────────────────────────────────


def test_install_local_zip(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    _write_manifest(src_dir, name="zipped")
    archive_path = tmp_path / "demo.zip"
    payload = {"SKILL.md": (src_dir / "SKILL.md").read_text()}
    archive_path.write_bytes(_make_zip(payload))

    store = InMemorySkillStore()
    agent_id = uuid4()
    result = install_external(
        str(archive_path), agent_id, store=store, agents_root=tmp_path / "agents"
    )
    assert result.skill_id is not None
    assert result.target_path.name == "zipped"


def test_install_zip_with_wrapper_dir(tmp_path: Path) -> None:
    """GitHub-style archives wrap content in a single top-level directory."""
    src_dir = tmp_path / "src"
    _write_manifest(src_dir, name="wrapped")
    archive_path = tmp_path / "demo.zip"
    payload = {"repo-main/SKILL.md": (src_dir / "SKILL.md").read_text()}
    archive_path.write_bytes(_make_zip(payload))

    store = InMemorySkillStore()
    agent_id = uuid4()
    result = install_external(
        str(archive_path), agent_id, store=store, agents_root=tmp_path / "agents"
    )
    assert result.manifest.name == "wrapped"
    assert (result.target_path / "SKILL.md").exists()


def test_install_zip_rejects_path_traversal(tmp_path: Path) -> None:
    archive_path = tmp_path / "evil.zip"
    archive_path.write_bytes(_make_zip({"../escape/SKILL.md": "name: x"}))

    with pytest.raises(SkillInstallError, match="unsafe zip member"):
        install_external(
            str(archive_path),
            uuid4(),
            store=InMemorySkillStore(),
            agents_root=tmp_path / "agents",
        )


def test_install_zip_rejects_invalid_archive(tmp_path: Path) -> None:
    archive_path = tmp_path / "broken.zip"
    archive_path.write_bytes(b"not a real zip")
    with pytest.raises(SkillInstallError, match="Invalid zip archive"):
        install_external(
            str(archive_path),
            uuid4(),
            store=InMemorySkillStore(),
            agents_root=tmp_path / "agents",
        )


def test_install_zip_rejects_symlink_member(tmp_path: Path) -> None:
    """Devin Review _0004: refuse symlink members so a malicious archive
    cannot point shutil.copytree at a file outside the staging dir.
    """
    archive_path = tmp_path / "evil-symlink.zip"
    # Hand-construct a zip with a symlink member. ZipInfo.external_attr
    # encodes the unix file type in the upper 16 bits; 0xA000 is S_IFLNK.
    with zipfile.ZipFile(archive_path, "w") as zf:
        info = zipfile.ZipInfo("evil-link")
        info.external_attr = (0xA1FF & 0xFFFF) << 16  # S_IFLNK | 0o777
        zf.writestr(info, "/etc/passwd")
        zf.writestr("SKILL.md", "name: ok\ndescription: ok\n")

    with pytest.raises(SkillInstallError, match="non-regular zip member"):
        install_external(
            str(archive_path),
            uuid4(),
            store=InMemorySkillStore(),
            agents_root=tmp_path / "agents",
        )


# ── HTTPS source ──────────────────────────────────────────────────────────


def test_install_https_uses_injected_http_get(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    _write_manifest(src_dir, name="remote")
    archive_bytes = _make_zip({"SKILL.md": (src_dir / "SKILL.md").read_text()})

    calls: list[str] = []

    def fake_get(url: str) -> bytes:
        calls.append(url)
        return archive_bytes

    store = InMemorySkillStore()
    result = install_external(
        "https://example.com/remote.zip",
        uuid4(),
        store=store,
        agents_root=tmp_path / "agents",
        http_get=fake_get,
    )
    assert calls == ["https://example.com/remote.zip"]
    assert result.manifest.name == "remote"


def test_install_https_propagates_download_error(tmp_path: Path) -> None:
    def fake_get(url: str) -> bytes:
        raise RuntimeError("network down")

    with pytest.raises(SkillInstallError, match="Download failed"):
        install_external(
            "https://example.com/x.zip",
            uuid4(),
            store=InMemorySkillStore(),
            agents_root=tmp_path / "agents",
            http_get=fake_get,
        )


def test_install_rejects_plain_http(tmp_path: Path) -> None:
    with pytest.raises(SkillInstallError, match="HTTP is not supported"):
        install_external(
            "http://example.com/x.zip",
            uuid4(),
            store=InMemorySkillStore(),
            agents_root=tmp_path / "agents",
        )


def test_install_rejects_bare_github_url(tmp_path: Path) -> None:
    with pytest.raises(SkillInstallError, match="GitHub URLs"):
        install_external(
            "https://github.com/user/repo",
            uuid4(),
            store=InMemorySkillStore(),
            agents_root=tmp_path / "agents",
        )


def test_install_overrides_in_session_origin_to_external(tmp_path: Path) -> None:
    """Even if the manifest claims origin=in_session, store row is external."""
    src = tmp_path / "src"
    src.mkdir()
    write_skill_md(
        SkillManifest(
            name="claims-in-session",
            description="d",
            origin=SkillOrigin.in_session,
            body="x",
        ),
        src / "SKILL.md",
    )
    store = InMemorySkillStore()
    agent_id = uuid4()
    result = install_external(str(src), agent_id, store=store, agents_root=tmp_path / "agents")
    assert result.manifest.origin == SkillOrigin.external
    stored = store.get_skill_by_name(agent_id, "claims-in-session")
    assert stored is not None
    assert stored.origin == SkillOrigin.external
