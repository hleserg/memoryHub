"""
atman/agent_cli/search.py
Web search via DuckDuckGo (free, no API key).

Strategy:
  1. Search on priority dev sites first (GitHub, SO, docs, etc.)
  2. Fetch top results and extract content via trafilatura
  3. If results are thin → expand to general web
  4. Agent can also extend the known site list at runtime

Install: pip install duckduckgo-search
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

# ── Priority site registry ────────────────────────────────────────────────────

# Ordered by relevance to programming/AI tasks.
# Agent searches these first, expands if results are thin.
DEV_SITES: list[dict] = [
    # Code & docs
    {"domain": "github.com", "label": "GitHub", "tags": ["code", "repos", "issues"]},
    {"domain": "stackoverflow.com", "label": "Stack Overflow", "tags": ["qa", "python", "errors"]},
    {"domain": "docs.python.org", "label": "Python Docs", "tags": ["python", "stdlib", "docs"]},
    {"domain": "pypi.org", "label": "PyPI", "tags": ["packages", "libraries"]},
    {"domain": "readthedocs.io", "label": "ReadTheDocs", "tags": ["docs", "libraries"]},
    {"domain": "realpython.com", "label": "Real Python", "tags": ["python", "tutorials"]},
    {"domain": "pydantic.dev", "label": "Pydantic Docs", "tags": ["pydantic", "validation"]},
    {"domain": "fastapi.tiangolo.com", "label": "FastAPI Docs", "tags": ["api", "fastapi"]},
    # AI/ML
    {"domain": "huggingface.co", "label": "Hugging Face", "tags": ["models", "ml", "transformers"]},
    {"domain": "arxiv.org", "label": "arXiv", "tags": ["papers", "research", "ml"]},
    {
        "domain": "docs.anthropic.com",
        "label": "Anthropic Docs",
        "tags": ["claude", "anthropic", "api"],
    },
    # Tooling
    {"domain": "docs.docker.com", "label": "Docker Docs", "tags": ["docker", "containers"]},
    {"domain": "docs.github.com", "label": "GitHub Docs", "tags": ["github", "actions", "ci"]},
    {"domain": "mypy.readthedocs.io", "label": "mypy", "tags": ["types", "mypy"]},
    {"domain": "docs.astral.sh", "label": "Astral (ruff/uv)", "tags": ["ruff", "uv", "linting"]},
    {"domain": "textual.textualize.io", "label": "Textual Docs", "tags": ["textual", "tui"]},
    # General dev reference
    {"domain": "developer.mozilla.org", "label": "MDN", "tags": ["web", "js", "html", "css"]},
    {"domain": "devdocs.io", "label": "DevDocs", "tags": ["reference", "docs"]},
]

# Site domains in priority order (for site: query building)
PRIORITY_DOMAINS = [s["domain"] for s in DEV_SITES]

# Minimum content chars to consider search results "good enough"
MIN_CONTENT_CHARS = 800
# How many results to fetch per search
MAX_RESULTS = 5
# How many results to actually fetch content from
MAX_FETCH = 3


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    content: str = ""  # fetched full content
    domain: str = ""
    source: str = "ddg"

    @property
    def ok(self) -> bool:
        return bool(self.content or self.snippet)

    def to_context(self, max_chars: int = 3000) -> str:
        body = self.content or self.snippet
        if len(body) > max_chars:
            body = body[:max_chars] + "\n[... truncated ...]"
        return f"## {self.title}\n{self.url}\n\n{body}"


@dataclass
class SearchSession:
    query: str
    results: list[SearchResult] = field(default_factory=list)
    expanded: bool = False  # True if we had to fall back to general web
    searched_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))

    def to_context(self, max_results: int = 3) -> str:
        if not self.results:
            return f"No results found for: {self.query}"
        parts = [
            f"## Search results for: {self.query}"
            + (" (expanded to general web)" if self.expanded else " (dev sites)"),
            "",
        ]
        for r in self.results[:max_results]:
            if r.ok:
                parts.append(r.to_context())
                parts.append("")
        return "\n".join(parts)


# ── Search functions ──────────────────────────────────────────────────────────


def _ddg_search(query: str, max_results: int = MAX_RESULTS) -> list[dict]:
    """Raw DuckDuckGo search. Returns list of {title, href, body}."""
    try:
        from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))
    except ImportError:
        raise RuntimeError(
            "duckduckgo-search not installed: pip install duckduckgo-search"
        ) from None
    except Exception as e:
        raise RuntimeError(f"DuckDuckGo search error: {e}") from e


def _build_site_query(base_query: str, domains: list[str]) -> str:
    """Build a DuckDuckGo query restricted to specific sites."""
    site_filter = " OR ".join(f"site:{d}" for d in domains[:8])  # DDG handles ~8 site: ops
    return f"{base_query} ({site_filter})"


def _fetch_result_content(url: str) -> str:
    """Fetch content from a URL using web.py."""
    try:
        from .web import fetch_github_raw, fetch_url, is_github_url

        if is_github_url(url):
            page = fetch_github_raw(url)
        else:
            page = fetch_url(url)
        return page.content if page.ok else ""
    except Exception:
        return ""


def _relevant_domains_for_query(query: str) -> list[str]:
    """
    Pick the most relevant domains based on query keywords.
    Returns a prioritized subset of DEV_SITES domains.
    """
    query_lower = query.lower()
    scored: list[tuple[int, str]] = []

    for site in DEV_SITES:
        score = 0
        for tag in site["tags"]:
            if tag in query_lower:
                score += 2
        if site["domain"].split(".")[0] in query_lower:
            score += 3
        scored.append((score, site["domain"]))

    # Sort by score desc, then fallback to original order
    scored.sort(key=lambda x: -x[0])

    # Always include top-tier sites regardless of score
    top_always = ["github.com", "stackoverflow.com", "docs.python.org"]
    result = top_always[:]
    for _, domain in scored:
        if domain not in result:
            result.append(domain)

    return result


def search(
    query: str,
    fetch_content: bool = True,
    force_general: bool = False,
    extra_domains: list[str] | None = None,
) -> SearchSession:
    """
    Main search function.

    1. Search priority dev sites (or relevant subset)
    2. Optionally fetch content from top results
    3. If content is thin → expand to general web
    4. Returns SearchSession with results and context

    Args:
        query:          The search query
        fetch_content:  Whether to fetch full page content (slower but richer)
        force_general:  Skip dev-site restriction, go straight to general web
        extra_domains:  Additional domains to include in priority search
    """
    session = SearchSession(query=query)

    if force_general:
        return _search_general(session, query, fetch_content)

    # Step 1: Dev-site search
    relevant_domains = _relevant_domains_for_query(query)
    if extra_domains:
        for d in extra_domains:
            if d not in relevant_domains:
                relevant_domains.insert(2, d)  # after top-tier

    site_query = _build_site_query(query, relevant_domains[:8])

    try:
        raw = _ddg_search(site_query, max_results=MAX_RESULTS)
    except RuntimeError as e:
        session.results.append(SearchResult(title="Search error", url="", snippet=str(e)))
        return session

    # Convert to SearchResult
    for item in raw:
        from urllib.parse import urlparse

        domain = urlparse(item.get("href", "")).netloc
        session.results.append(
            SearchResult(
                title=item.get("title", ""),
                url=item.get("href", ""),
                snippet=item.get("body", ""),
                domain=domain,
            )
        )

    # Step 2: Fetch content from top results
    if fetch_content:
        _fetch_contents(session)

    # Step 3: Check if content is rich enough
    total_content = sum(len(r.content) for r in session.results)
    if total_content < MIN_CONTENT_CHARS and not force_general:
        # Expand to general web
        return _search_general(session, query, fetch_content)

    return session


def _search_general(
    session: SearchSession,
    query: str,
    fetch_content: bool,
) -> SearchSession:
    """Fallback: search general web without site restriction."""
    session.expanded = True

    try:
        raw = _ddg_search(query, max_results=MAX_RESULTS)
    except RuntimeError:
        return session

    from urllib.parse import urlparse

    for item in raw:
        domain = urlparse(item.get("href", "")).netloc
        # Skip if already in results
        existing_urls = {r.url for r in session.results}
        if item.get("href") in existing_urls:
            continue
        session.results.append(
            SearchResult(
                title=item.get("title", ""),
                url=item.get("href", ""),
                snippet=item.get("body", ""),
                domain=domain,
            )
        )

    if fetch_content:
        _fetch_contents(session)

    return session


def _fetch_contents(session: SearchSession) -> None:
    """Fetch full content for results that don't have it yet."""
    fetched = 0
    for result in session.results:
        if fetched >= MAX_FETCH:
            break
        if result.content or not result.url:
            continue
        result.content = _fetch_result_content(result.url)
        if result.content:
            fetched += 1


# ── Search intent detection ───────────────────────────────────────────────────

# Patterns that suggest the user wants a web search
SEARCH_INTENT_PATTERNS = [
    r"\b(найди|поищи|погугли|look up|search for|find out|how to|как сделать|как написать)\b",
    r"\b(что такое|what is|what are|объясни|explain)\b",
    r"\b(покажи пример|show me|give me an example|дай пример)\b",
    r"\b(документация|docs|api reference|readme)\b.*\bдля\b",
    r"\b(как использовать|how to use|tutorial|туториал)\b",
    r"\b(лучший способ|best way|best practice|best approach)\b",
    r"\b(сравни|compare|vs\.?|versus|отличие)\b",
    r"\b(последняя версия|latest version|changelog|release)\b",
    r"\b(ошибка|error|exception|traceback)\b.*\b(что значит|why|почему)\b",
    r"\b(посмотри в интернете|search online|check online)\b",
]

_SEARCH_RE = re.compile(
    "|".join(SEARCH_INTENT_PATTERNS),
    re.IGNORECASE,
)


def has_search_intent(text: str) -> bool:
    """Detect if a message is asking the agent to search the web."""
    return bool(_SEARCH_RE.search(text))


def extract_search_query(text: str, llm_extract_fn=None) -> str:
    """
    Extract the actual search query from a natural language request.
    If llm_extract_fn provided, use LLM; otherwise use heuristics.
    """
    # Strip common preambles
    text = re.sub(
        r"^(найди|поищи|погугли|look up|search for|find|покажи|объясни|explain)\s*",
        "",
        text.strip(),
        flags=re.IGNORECASE,
    )
    text = re.sub(r"^(мне|me|please|пожалуйста)\s+", "", text, flags=re.IGNORECASE)
    return text.strip()


# ── Domain management (runtime extensible) ────────────────────────────────────

_extra_domains: list[str] = []


def add_search_domain(domain: str, label: str = "", tags: list[str] | None = None) -> None:
    """Add a domain to the priority search list at runtime."""
    global _extra_domains
    if domain not in [s["domain"] for s in DEV_SITES] and domain not in _extra_domains:
        _extra_domains.append(domain)
        DEV_SITES.append(
            {
                "domain": domain,
                "label": label or domain,
                "tags": tags or [],
            }
        )


def get_known_sites() -> list[dict]:
    return DEV_SITES


SEARCH_HISTORY_PATH = Path.home() / ".atman" / "agent_memory" / "search_history.jsonl"


@dataclass
class SearchHistoryEntry:
    query: str
    timestamp: str  # ISO
    results_count: int
    session_id: str


class SearchHistory:
    def __init__(self, path: Path | str = SEARCH_HISTORY_PATH):
        self.path = Path(path)

    def record(self, query: str, results_count: int, session_id: str = "") -> None:
        entry = SearchHistoryEntry(
            query=query,
            timestamp=datetime.now(UTC).isoformat(),
            results_count=results_count,
            session_id=session_id,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry)) + "\n")

    def load_recent(self, n: int = 10) -> list[SearchHistoryEntry]:
        if not self.path.exists():
            return []
        lines = [ln for ln in self.path.read_text().splitlines() if ln.strip()]
        return [SearchHistoryEntry(**json.loads(ln)) for ln in lines[-n:]]

    def format_list(self, entries: list[SearchHistoryEntry]) -> str:
        if not entries:
            return "(no search history)"
        lines = ["Recent searches:"]
        for i, e in enumerate(entries, 1):
            date = e.timestamp[:10]
            lines.append(f"  {i}. [{date}] {e.query} ({e.results_count} results)")
        return "\n".join(lines)
