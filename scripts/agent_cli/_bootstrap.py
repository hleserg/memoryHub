"""Load `atman` and nested `atman.agent_cli` from a split-repo checkout."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def repo_paths(repo: Path) -> tuple[Path, Path]:
    """Return (agent_cli_src, core_src) in README order."""

    repo = repo.resolve()
    return repo / "atman_agent_cli" / "src", repo / "src"


def prepend_sys_path(agent_cli_src: Path, core_src: Path) -> None:
    """Prefer `PYTHONPATH=atman_agent_cli/src:src` (documentation order)."""

    for p in (agent_cli_src, core_src):
        s = str(p)
        while s in sys.path:
            sys.path.remove(s)
        sys.path.insert(0, s)


def bootstrap_atman_agent_cli(repo: Path) -> None:
    """
    Insert source roots, import core `atman`, then attach `atman.agent_cli`.

    Plain dual-path imports fail today because core `src/atman/__init__.py`
    shadows the-namespace merge; tooling registers `atman.agent_cli` explicitly.
    """

    agent_cli_src, core_src = repo_paths(repo)
    prepend_sys_path(agent_cli_src, core_src)

    import atman as atman_pkg

    init_path = agent_cli_src / "atman" / "agent_cli" / "__init__.py"
    agent_cli_pkg_dir = agent_cli_src / "atman" / "agent_cli"
    spec = importlib.util.spec_from_file_location(
        "atman.agent_cli",
        init_path,
        submodule_search_locations=[str(agent_cli_pkg_dir)],
    )
    if spec is None or spec.loader is None:
        msg = "Could not load atman.agent_cli from split layout."
        raise ImportError(msg)

    acl = importlib.util.module_from_spec(spec)
    sys.modules["atman.agent_cli"] = acl
    atman_pkg.agent_cli = acl
    spec.loader.exec_module(acl)
