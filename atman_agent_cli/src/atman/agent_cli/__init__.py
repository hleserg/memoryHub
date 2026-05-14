"""
Atman Agent CLI — Textual TUI local coding agent (optional adjunct to core `src/atman`).

Install extras: pip install -e ".[agent-cli]" and set PYTHONPATH=atman_agent_cli/src:src
(see `atman_agent_cli/README.md`).

Core code must never import `atman.agent_cli` (import linter contract in repo root).
"""

from .cli import main, AtmanApp
from .config import AgentConfig

__all__ = ["AgentConfig", "AtmanApp", "main"]
