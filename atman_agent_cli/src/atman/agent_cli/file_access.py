"""
atman/agent_cli/file_access.py
Safe filesystem access: read broadly; mutate only inside repo_root.

CLI Integration Notes:
  At startup use: repo_root, work_dir = SafeFileExplorer.get_work_dir()
  Show in TUI header: atman-agent — {work_dir.name} — {branch}
  Command /pwd → show work_dir and repo_root.
  If agent calls write() outside repo → catch FileAccessPermissionError (also ``except PermissionError``) → warn + prompt [y/N].
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path


class FileAccessPermissionError(PermissionError):
    """Raised when a mutating operation is denied (outside repo or unconfirmed exec)."""


class SafeFileExplorer:
    """
    Read anywhere. Write/delete/execute only inside repo_root.
    Outside repo — read-only.
    """

    def __init__(self, repo_root: Path, work_dir: Path) -> None:
        self.repo_root = repo_root.resolve()
        self.work_dir = work_dir.resolve()

    def read(self, path: str | Path) -> str:
        """Read any file. Auto OCR for raster images."""
        p = Path(path).resolve()
        if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
            from .ocr import OCRProcessor

            return OCRProcessor().extract_text(p)
        if p.suffix.lower() == ".pdf":
            return self._read_pdf(p)
        return p.read_text(encoding="utf-8", errors="replace")

    def _read_pdf(self, path: Path) -> str:
        try:
            from pdfminer.high_level import extract_text

            return extract_text(str(path))
        except ImportError:
            return "[PDF reading requires: pip install pdfminer.six]"

    def list_dir(self, path: Path | str) -> list[Path]:
        """List directory entries."""
        return list(Path(path).iterdir())

    def search(
        self, pattern: str, root: Path | str | None = None, recursive: bool = True
    ) -> list[Path]:
        """Find files matching a glob pattern."""
        root_path = Path(root or self.work_dir)
        if recursive:
            return list(root_path.rglob(pattern))
        return list(root_path.glob(pattern))

    def write(self, path: Path | str, content: str) -> None:
        """Write only inside repo_root."""
        p = Path(path).resolve()
        if not p.is_relative_to(self.repo_root):
            raise FileAccessPermissionError(f"Write outside repo is forbidden: {p}")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def delete(self, path: Path | str) -> None:
        """Delete only inside repo_root."""
        p = Path(path).resolve()
        if not p.is_relative_to(self.repo_root):
            raise FileAccessPermissionError(f"Delete outside repo is forbidden: {p}")
        p.unlink()

    def execute(self, cmd: str, confirm_callback: Callable[[], bool] | None = None) -> str:
        """
        Run a shell command only with explicit confirmation.
        confirm_callback: callable() -> bool. If None — always refuse.
        """
        if confirm_callback is None or not confirm_callback():
            raise FileAccessPermissionError("Execution requires explicit user confirmation")
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=False)
        return result.stdout + result.stderr

    @staticmethod
    def find_git_root(start: Path) -> Path | None:
        """Find git repository root starting from start."""
        current = start.resolve()
        while current != current.parent:
            if (current / ".git").exists():
                return current
            current = current.parent
        return None

    @staticmethod
    def get_work_dir() -> tuple[Path, Path]:
        """
        Return (repo_root, work_dir).
        repo_root = git root or cwd if not in a git repo.
        """
        work_dir = Path.cwd()
        repo_root = SafeFileExplorer.find_git_root(work_dir) or work_dir
        return repo_root, work_dir
