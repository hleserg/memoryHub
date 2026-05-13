"""
atman/agent_cli/__init__.py
Atman Agent CLI — Textual TUI local coding agent.
Not included in production release. Install with: pip install atman[agent]
"""
from .cli import main, AtmanApp
from .config import AgentConfig

__all__ = ["main", "AtmanApp", "AgentConfig"]

# pyproject.toml additions:
#
# [project.optional-dependencies]
# agent = [
#     "textual>=0.60",
#     "requests>=2.31",
#     "cohere>=5.0",
#     "anthropic>=0.25",
#     "FlagEmbedding>=1.2",
#     "numpy>=1.24",
# ]
#
# [project.scripts]
# atman-agent = "atman.agent_cli.cli:main"
#
# .importlinter — prevent prod from importing agent_cli:
# [importlinter:contract:no-agent-in-prod]
# name = Production must not import agent_cli
# type = forbidden
# source_modules = atman.core, atman.adapters, atman.affect
# forbidden_modules = atman.agent_cli
