"""HLE-38 — install external skills from a local path or HTTPS .zip URL.

Pure, side-effecting installer for ``atman-skills install-external``.
Decoupled from the CLI so it can be unit-tested without spawning a
subprocess or hitting the real internet.

Supported sources:

* ``/local/path/to/skill/``     — directory containing ``SKILL.md``
* ``/local/path/to/skill.zip``  — local zip archive
* ``https://…/skill.zip``       — HTTPS zip archive (HTTP not allowed)

Out of scope (deferred):
* ``git clone`` / GitHub repo URLs — point the user at the ``/archive/HEAD.zip``
  URL instead. Pulling git remotes from a CLI installer is a meaningful
  security and dependency surface (git binary, SSH keys, refspec parsing)
  that should land in its own PR with explicit review.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from atman.skills.manifest import SkillManifest, parse_skill_md
from atman.skills.models import Skill, SkillOrigin, SkillStatus
from atman.skills.store import SkillStore

_log = logging.getLogger(__name__)


class SkillInstallError(RuntimeError):
    """Raised when an install attempt fails for any reason the user must see."""


@dataclass(frozen=True)
class InstallResult:
    """Outcome of an install attempt (dry-run or live)."""

    manifest: SkillManifest
    target_path: Path  # final on-disk root (skill_root)
    dry_run: bool
    skill_id: UUID | None  # None for dry-run
    runtime_warning: bool  # True when the manifest declares a runtime_entry


# ── public entry point ────────────────────────────────────────────────────


def install_external(
    source: str,
    agent_id: UUID,
    *,
    store: SkillStore,
    agents_root: Path,
    name_override: str | None = None,
    dry_run: bool = False,
    http_get: Callable[[str], bytes] | None = None,
) -> InstallResult:
    """Install a skill from ``source`` for ``agent_id``.

    Parameters
    ----------
    source
        Local path or HTTPS .zip URL. See module docstring for the matrix.
    agent_id
        Target agent — the skill is installed under
        ``agents_root/<agent_id>/skills/<name>/``.
    store
        Concrete :class:`SkillStore` to record the new skill in.
    agents_root
        Root of the on-disk agent directory tree (typically
        ``~/.atman/agents``).
    name_override
        When set, the installed skill is renamed (manifest ``name`` is
        rewritten on disk and used as the directory leaf).
    dry_run
        Validate + report without writing anything (no DB row, no copy).
    http_get
        Optional injected ``(url) -> bytes`` callable for tests; defaults
        to a minimal :mod:`httpx` download.

    Raises
    ------
    SkillInstallError
        On any user-visible failure (missing manifest, name collision,
        download error, etc).
    """
    with tempfile.TemporaryDirectory(prefix="atman-skill-install-") as td:
        staging = Path(td)
        manifest_dir = _materialise_source(source, staging, http_get=http_get)
        manifest_path = manifest_dir / "SKILL.md"
        if not manifest_path.exists():
            raise SkillInstallError(
                f"No SKILL.md at the root of '{source}' (looked in {manifest_dir})"
            )

        manifest = parse_skill_md(manifest_path)

        # Apply name override and re-validate.
        if name_override:
            manifest = _rename_manifest(manifest, name_override, manifest_path)

        # Mark as externally-installed even if the source manifest claimed otherwise.
        if manifest.origin != SkillOrigin.external:
            manifest = SkillManifest(
                **{**manifest.__dict__, "origin": SkillOrigin.external},
            )

        _validate_manifest(manifest)

        target_root = agents_root / str(agent_id) / "skills" / manifest.name
        if not dry_run and target_root.exists():
            raise SkillInstallError(
                f"Target directory already exists: {target_root}. "
                "Disable + archive the old skill first."
            )

        # Name uniqueness in the store.
        if not dry_run and store.get_skill_by_name(agent_id, manifest.name) is not None:
            raise SkillInstallError(
                f"A skill named '{manifest.name}' is already registered for agent {agent_id}. "
                "Use --name <override> or remove the existing skill first."
            )

        runtime_warning = bool(manifest.runtime_entry)

        if dry_run:
            return InstallResult(
                manifest=manifest,
                target_path=target_root,
                dry_run=True,
                skill_id=None,
                runtime_warning=runtime_warning,
            )

        # Copy into the agent's skills tree. Use copytree to preserve scripts.
        target_root.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(manifest_dir, target_root)

        # Rewrite the manifest in the target tree so on-disk reflects any
        # overrides (origin, name) we applied above.
        from atman.skills.manifest import write_skill_md

        write_skill_md(manifest, target_root / "SKILL.md")

        now = datetime.now(UTC)
        skill = Skill(
            id=uuid4(),
            agent_id=agent_id,
            entity_id=uuid4(),
            name=manifest.name,
            description=manifest.description,
            version=manifest.version,
            kind=manifest.kind,
            status=SkillStatus.active,  # external installs are active immediately
            origin=SkillOrigin.external,
            core=manifest.core,
            session_scoped=manifest.session_scoped,
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
            manifest_inferred=manifest.manifest_inferred,
            skill_root=target_root,
            manifest_path=target_root / "SKILL.md",
            created_at=now,
            updated_at=now,
        )
        store.save_skill(skill)

        _log.info(
            "Installed external skill '%s' (id=%s, runtime=%s) for agent %s",
            manifest.name,
            skill.id,
            manifest.runtime_entry or "none",
            agent_id,
        )
        return InstallResult(
            manifest=manifest,
            target_path=target_root,
            dry_run=False,
            skill_id=skill.id,
            runtime_warning=runtime_warning,
        )


# ── source acquisition ────────────────────────────────────────────────────


def _materialise_source(
    source: str,
    staging: Path,
    *,
    http_get: Callable[[str], bytes] | None,
) -> Path:
    """Bring ``source`` into ``staging`` and return the dir containing SKILL.md."""
    s = source.strip()
    if not s:
        raise SkillInstallError("Source is empty")

    # Reject unsupported HTTP scheme (security: do not silently downgrade).
    if s.startswith("http://"):
        raise SkillInstallError("HTTP is not supported — use HTTPS so the archive is verified.")

    # Block bare GitHub repo URLs with a useful hint.
    if s.startswith("https://github.com/") and not s.endswith(".zip"):
        raise SkillInstallError(
            "Bare GitHub URLs are not yet supported. "
            "Pass the archive URL directly, e.g. "
            "https://github.com/USER/REPO/archive/refs/heads/main.zip"
        )

    if s.startswith("https://"):
        return _fetch_zip_url(s, staging, http_get=http_get)

    path = Path(s).expanduser().resolve()
    if not path.exists():
        raise SkillInstallError(f"Source path does not exist: {path}")
    if path.is_dir():
        # Use directory in place; copy into staging so we can normalise the
        # manifest without touching the original.
        copy_root = staging / "src"
        shutil.copytree(path, copy_root)
        return _locate_manifest_root(copy_root)
    if path.suffix.lower() == ".zip":
        return _extract_zip(path, staging)
    raise SkillInstallError(f"Unsupported source: {path} (expected directory or .zip file)")


def _fetch_zip_url(
    url: str,
    staging: Path,
    *,
    http_get: Callable[[str], bytes] | None,
) -> Path:
    """Download ``url`` to ``staging/download.zip`` and extract."""
    if http_get is None:
        http_get = _default_http_get
    try:
        data = http_get(url)
    except Exception as exc:
        raise SkillInstallError(f"Download failed: {exc}") from exc
    archive = staging / "download.zip"
    archive.write_bytes(data)
    return _extract_zip(archive, staging)


def _default_http_get(url: str) -> bytes:
    """Minimal HTTPS GET — kept inside a helper so tests can inject a fake."""
    import httpx

    with httpx.Client(follow_redirects=True, timeout=30.0) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.content


def _extract_zip(archive: Path, staging: Path) -> Path:
    extracted = staging / "extracted"
    extracted.mkdir(exist_ok=True)
    try:
        with zipfile.ZipFile(archive) as zf:
            # Defend against zip-slip + symlink escape. ``zipfile`` does not
            # restrict the targets of zip-stored symlinks, so a malicious
            # archive could plant a symlink that ``shutil.copytree`` (which
            # follows symlinks by default) then dereferences during the
            # copy into the agent's skill directory.
            for info in zf.infolist():
                norm = Path(info.filename)
                if norm.is_absolute() or ".." in norm.parts:
                    raise SkillInstallError(f"Refusing unsafe zip member: {info.filename}")
                # Symlink/hardlink/device members carry a non-zero file type
                # in the external attr's upper 16 bits. 0xA000 is S_IFLNK
                # (symlink). Refuse everything that isn't a regular file or
                # directory.
                file_type = (info.external_attr >> 16) & 0xF000
                if file_type and file_type not in (0x8000, 0x4000):  # regular | directory
                    raise SkillInstallError(
                        f"Refusing non-regular zip member: {info.filename} (type={file_type:#x})"
                    )
            zf.extractall(extracted)
    except zipfile.BadZipFile as exc:
        raise SkillInstallError(f"Invalid zip archive: {exc}") from exc
    return _locate_manifest_root(extracted)


def _locate_manifest_root(root: Path) -> Path:
    """Find the directory containing SKILL.md. Tolerates one wrapper dir
    (common for GitHub archives) but no deeper to keep the resolution
    unambiguous.
    """
    if (root / "SKILL.md").exists():
        return root
    candidates = [p for p in root.iterdir() if p.is_dir()]
    if len(candidates) == 1 and (candidates[0] / "SKILL.md").exists():
        return candidates[0]
    raise SkillInstallError(
        f"No SKILL.md found at the top of {root} (or inside a single wrapper dir)"
    )


# ── manifest helpers ──────────────────────────────────────────────────────


def _rename_manifest(manifest: SkillManifest, new_name: str, manifest_path: Path) -> SkillManifest:
    """Apply ``--name`` override; the new name must be kebab-case alphanumeric."""
    if not _valid_skill_name(new_name):
        raise SkillInstallError(
            f"--name '{new_name}' must be kebab-case alphanumeric (letters, digits, dashes, underscores)"
        )
    return SkillManifest(
        **{**manifest.__dict__, "name": new_name},
    )


def _validate_manifest(manifest: SkillManifest) -> None:
    if not _valid_skill_name(manifest.name):
        raise SkillInstallError(
            f"Manifest 'name' is not kebab-case alphanumeric: {manifest.name!r}"
        )
    if not manifest.description.strip():
        raise SkillInstallError("Manifest 'description' is empty")


def _valid_skill_name(name: str) -> bool:
    if not name:
        return False
    return name.replace("-", "").replace("_", "").isalnum()
