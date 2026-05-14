"""
atman/agent_cli/secrets.py
Secrets management — single source of truth for API keys.

Priority (highest to lowest):
  1. Runtime overrides (set via /config in CLI)
  2. Environment variables
  3. ~/.atman/.secrets file
  4. .env in repo root (dev convenience, must be gitignored)

~/.atman/.secrets format (simple KEY=VALUE, no quotes needed):
  ANTHROPIC_API_KEY=sk-ant-...
  COHERE_API_KEY=...
  GITHUB_TOKEN=ghp_...
  ATMAN_LLM_URL=http://localhost:8080

Never commit secrets to git. ~/.atman/ is outside the repo by default.
"""
from __future__ import annotations

import os
from pathlib import Path


_SECRETS_FILE = Path.home() / ".atman" / ".secrets"
_REPO_ENV_FILE = Path(".env")   # dev convenience, gitignored

# Known keys and their env var names
KNOWN_KEYS = {
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "cohere_api_key":    "COHERE_API_KEY",
    "github_token":      "GITHUB_TOKEN",
    "atman_llm_url":     "ATMAN_LLM_URL",
    "atman_llm_model":   "ATMAN_LLM_MODEL",
    "atman_webhook_port":"ATMAN_WEBHOOK_PORT",
}


class SecretsManager:
    """
    Loads secrets from files and env vars. Supports runtime overrides.
    Writes back to ~/.atman/.secrets when secrets are updated via /config.
    """

    def __init__(self) -> None:
        self._file_values: dict[str, str] = {}
        self._runtime: dict[str, str] = {}
        self._reload_files()

    def _reload_files(self) -> None:
        """Load from .secrets and .env files."""
        self._file_values = {}

        # .env in repo root (lower priority)
        for path in [_REPO_ENV_FILE, _SECRETS_FILE]:
            if path.exists():
                for line in path.read_text().splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, _, v = line.partition("=")
                        self._file_values[k.strip().upper()] = v.strip()

    def get(self, key: str, default: str = "") -> str:
        """
        Get a secret. Priority: runtime > env var > file.
        key is case-insensitive.
        """
        upper = key.upper()

        # 1. Runtime override (set via /config)
        if upper in self._runtime:
            return self._runtime[upper]

        # 2. Environment variable
        env_val = os.getenv(upper)
        if env_val:
            return env_val

        # 3. File
        return self._file_values.get(upper, default)

    def set_runtime(self, key: str, value: str) -> None:
        """Set a runtime override. Does NOT persist to disk."""
        self._runtime[key.upper()] = value

    def set_persistent(self, key: str, value: str) -> None:
        """Set a value and persist it to ~/.atman/.secrets."""
        upper = key.upper()
        self._runtime[upper] = value
        self._write_to_secrets_file(upper, value)

    def _write_to_secrets_file(self, key: str, value: str) -> None:
        _SECRETS_FILE.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        updated = False

        if _SECRETS_FILE.exists():
            for line in _SECRETS_FILE.read_text().splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    k, _, _ = stripped.partition("=")
                    if k.strip().upper() == key:
                        lines.append(f"{key}={value}")
                        updated = True
                        continue
                lines.append(line)

        if not updated:
            lines.append(f"{key}={value}")

        _SECRETS_FILE.write_text("\n".join(lines) + "\n")
        # Restrict permissions: owner read/write only
        _SECRETS_FILE.chmod(0o600)

    def status(self) -> dict[str, str]:
        """
        Return a display-safe status dict.
        Shows which keys are set and from where, but masks values.
        """
        result = {}
        for friendly, env_key in KNOWN_KEYS.items():
            if env_key in self._runtime:
                result[friendly] = f"[runtime] {'*' * 8}"
            elif os.getenv(env_key):
                result[friendly] = f"[env]     {'*' * 8}"
            elif env_key in self._file_values:
                result[friendly] = f"[file]    {'*' * 8}"
            else:
                result[friendly] = "[not set]"
        return result

    # Convenience properties
    @property
    def anthropic_api_key(self) -> str:
        return self.get("ANTHROPIC_API_KEY")

    @property
    def cohere_api_key(self) -> str:
        return self.get("COHERE_API_KEY")

    @property
    def github_token(self) -> str:
        return self.get("GITHUB_TOKEN")

    @property
    def llm_url(self) -> str:
        return self.get("ATMAN_LLM_URL", "http://localhost:8080")

    @property
    def llm_model(self) -> str:
        return self.get("ATMAN_LLM_MODEL", "gemma4")


# Singleton
_secrets: SecretsManager | None = None

def get_secrets() -> SecretsManager:
    global _secrets
    if _secrets is None:
        _secrets = SecretsManager()
    return _secrets
