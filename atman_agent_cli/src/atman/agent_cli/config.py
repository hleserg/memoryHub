"""
atman/agent_cli/config.py
Configuration for the Atman agent CLI.
Not included in production release — optional dependency [agent].
"""
from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class AgentConfig:
    # ── Repo ──────────────────────────────────────────────────────────
    repo_path: Path = field(default_factory=lambda: Path.cwd())
    main_branch: str = "main"

    # ── LLM: llama.cpp server ─────────────────────────────────────────
    llm_url: str = field(
        default_factory=lambda: os.getenv("ATMAN_LLM_URL", "http://localhost:8080")
    )
    llm_model: str = field(
        default_factory=lambda: os.getenv("ATMAN_LLM_MODEL", "gemma4")
    )
    llm_temperature: float = 0.2   # низкая для кода
    llm_max_tokens: int = 4096
    llm_timeout: int = 120

    # ── Planner: Cohere ───────────────────────────────────────────────
    cohere_api_key: str = field(
        default_factory=lambda: os.getenv("COHERE_API_KEY", "")
    )
    cohere_model: str = "command-r-plus"
    cohere_temperature: float = 0.3

    # ── GitHub ────────────────────────────────────────────────────────
    github_token: str = field(
        default_factory=lambda: os.getenv("GITHUB_TOKEN", "")
    )
    github_repo: str = field(
        default_factory=lambda: os.getenv("ATMAN_GITHUB_REPO", "hleserg/atman")
    )
    github_api: str = "https://api.github.com"

    # ── RAG ───────────────────────────────────────────────────────────
    embed_model: str = "BAAI/bge-m3"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    rag_top_k: int = 50        # BGE-M3 candidates
    rag_top_n: int = 5         # after reranker
    index_path: Path = field(
        default_factory=lambda: Path.home() / ".atman" / "agent_index"
    )

    # ── Memory (Atman) ────────────────────────────────────────────────
    memory_path: Path = field(
        default_factory=lambda: Path.home() / ".atman" / "agent_memory"
    )

    # ── Babysit ───────────────────────────────────────────────────────
    babysit_poll_interval: int = 30    # seconds
    babysit_max_fix_attempts: int = 5
    babysit_require_approval: bool = True  # if False → merge as soon as CI green

    # ── Context window ────────────────────────────────────────────────
    context_limit: int = field(
        default_factory=lambda: int(os.getenv("ATMAN_CONTEXT_LIMIT", "8192"))
    )
    context_warn_ratio: float = 0.80
    context_critical_ratio: float = 0.90

    # ── UI ────────────────────────────────────────────────────────────
    history_file: Path = field(
        default_factory=lambda: Path.home() / ".atman" / "agent_history"
    )

    def __post_init__(self) -> None:
        self.repo_path = Path(self.repo_path)
        self.index_path.mkdir(parents=True, exist_ok=True)
        self.memory_path.mkdir(parents=True, exist_ok=True)
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        self._settings_file = self.memory_path / "settings.json"
        self._load_settings()

    def _load_settings(self) -> None:
        """Load persisted settings overrides."""
        if not self._settings_file.exists():
            return
        try:
            import json
            data = json.loads(self._settings_file.read_text())
            for key, val in data.items():
                if hasattr(self, key):
                    setattr(self, key, val)
        except Exception:
            pass

    def save_settings(self) -> None:
        """Persist mutable settings to disk."""
        import json
        PERSIST_KEYS = [
            "main_branch", "llm_url", "llm_model", "llm_temperature",
            "llm_max_tokens", "llm_timeout", "cohere_model", "cohere_temperature",
            "github_repo", "rag_top_k", "rag_top_n",
            "babysit_poll_interval", "babysit_max_fix_attempts", "babysit_require_approval",
            "context_limit", "context_warn_ratio", "context_critical_ratio",
        ]
        data = {k: getattr(self, k) for k in PERSIST_KEYS}
        self._settings_file.write_text(json.dumps(data, indent=2))

    @property
    def github_headers(self) -> dict[str, str]:
        h = {"Accept": "application/vnd.github+json"}
        if self.github_token:
            h["Authorization"] = f"Bearer {self.github_token}"
        return h
