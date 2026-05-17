"""
Atomic file write helper (private to adapters layer).

Shared utility used by file-based adapters to persist text content without
exposing callers to partially rewritten files. Single source of truth for
the tempfile + fsync + chmod + os.replace pattern.
"""

import os
import tempfile
from pathlib import Path


def write_atomically(path: Path, content: str) -> None:
    """Write content to path via temp file + fsync + replace.

    Creates parent dirs if missing. Preserves existing file mode,
    defaults to 0o600. Atomic across crashes via os.replace.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    file_mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    temp_file = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    temp_path = Path(temp_file.name)

    try:
        with temp_file as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())

        temp_path.chmod(file_mode)
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)
