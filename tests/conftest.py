"""
Shared pytest fixtures and configuration for the Atman test suite.
"""

from __future__ import annotations

import os

import httpx
import pytest


def _fetch_ollama_installed_models() -> set[str] | None:
    """Return model names from Ollama ``/api/tags``, or ``None`` if the server is unreachable."""
    try:
        resp = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
        if resp.status_code != 200:
            return None
        names: set[str] = set()
        for m in resp.json().get("models") or []:
            if isinstance(m, dict) and (n := m.get("name")):
                names.add(str(n))
        return names
    except (httpx.ConnectError, httpx.TimeoutException, OSError, ValueError, TypeError):
        return None


def _required_ollama_models(item: pytest.Item) -> tuple[str, ...]:
    """Models a test file expects to be installed (see OllamaReflectionModel / OllamaEmbeddingAdapter)."""
    path_name = item.path.name
    if path_name == "test_postgres_facts.py":
        return (os.environ.get("OLLAMA_EMBED_MODEL", "qwen3-embedding:4b"),)
    return (os.environ.get("ATMAN_OLLAMA_MODEL", "qwen3.5:9b"),)


def _installed_has_model(installed: set[str], want: str) -> bool:
    """True if ``want`` is present under a common Ollama tag naming scheme."""
    want_l = want.lower()
    if want_l in {n.lower() for n in installed}:
        return True
    want_base = want.split(":")[0].lower()
    for n in installed:
        nl = n.lower()
        if nl == want_l or nl.startswith(want_l + ":"):
            return True
        if nl.split(":")[0] == want_base:
            return True
    return False


def _check_agent_llm_available() -> bool:
    """Check if the agent's LLM endpoint is available."""
    base_url = os.getenv("AGENT_LLM_BASE_URL", "http://localhost:8080/v1")
    try:
        # Try to reach the /models or health endpoint
        resp = httpx.get(f"{base_url.rstrip('/')}/models", timeout=2.0)
        return resp.status_code in (200, 404)  # 404 is ok, means endpoint exists
    except (httpx.ConnectError, httpx.TimeoutException, OSError):
        return False


def _check_atman_llm_available() -> bool:
    """Check if Atman's internal LLM endpoint is available."""
    base_url = os.getenv("ATMAN_LLM_BASE_URL", "http://localhost:8081/v1")
    try:
        resp = httpx.get(f"{base_url.rstrip('/')}/models", timeout=2.0)
        return resp.status_code in (200, 404)
    except (httpx.ConnectError, httpx.TimeoutException, OSError):
        return False


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "requires_llm: marks tests that need Atman's internal LLM endpoint (ATMAN_LLM_BASE_URL)",
    )
    config.addinivalue_line(
        "markers",
        "requires_agent_llm: marks tests that need the agent's LLM endpoint (AGENT_LLM_BASE_URL)",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Auto-skip tests marked ``requires_ollama``, ``requires_llm``, or ``requires_agent_llm`` when endpoints are unavailable."""
    skip_unreachable = pytest.mark.skip(reason="Ollama is not reachable at localhost:11434")
    skip_no_models = pytest.mark.skip(reason="Ollama returned no models (empty /api/tags)")

    installed = _fetch_ollama_installed_models()

    for item in items:
        # Check requires_agent_llm marker
        if "requires_agent_llm" in item.keywords:
            if not _check_agent_llm_available():
                base_url = os.getenv("AGENT_LLM_BASE_URL", "http://localhost:8080/v1")
                item.add_marker(
                    pytest.mark.skip(
                        reason=f"Agent LLM not available at {base_url}",
                    )
                )
            continue

        # Check requires_llm marker (Atman internal LLM)
        if "requires_llm" in item.keywords:
            if not _check_atman_llm_available():
                base_url = os.getenv("ATMAN_LLM_BASE_URL", "http://localhost:8081/v1")
                item.add_marker(
                    pytest.mark.skip(
                        reason=f"Atman LLM not available at {base_url}",
                    )
                )
            continue

        # Check requires_ollama marker (legacy)
        if "requires_ollama" not in item.keywords:
            continue

        if installed is None:
            item.add_marker(skip_unreachable)
            continue

        if not installed:
            item.add_marker(skip_no_models)
            continue

        required = _required_ollama_models(item)
        if not all(_installed_has_model(installed, r) for r in required):
            miss = ", ".join(required)
            item.add_marker(
                pytest.mark.skip(
                    reason=f"Ollama is missing required model(s) for this test: {miss}",
                )
            )
