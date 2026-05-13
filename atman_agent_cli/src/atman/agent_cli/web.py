"""
atman/agent_cli/web.py
Web content fetching — free, no API key needed.

Primary: trafilatura (article extraction, cleans ads/nav/boilerplate)
Fallback: requests + basic HTML stripping
Optional: playwright for JS-heavy pages (install separately)

Usage:
    from .web import extract_urls, fetch_url, fetch_all_urls

    urls = extract_urls(user_message)
    pages = fetch_all_urls(urls)
    context = format_pages_for_context(pages)
"""

from __future__ import annotations

import re
import shutil
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

# Regex that catches most URLs in plain text
URL_PATTERN = re.compile(
    r"https?://[^\s\)\]\}\"\'<>]+",
    re.IGNORECASE,
)

MAX_CONTENT_CHARS = 12_000  # truncate long pages
FETCH_TIMEOUT = 15  # seconds per URL
MAX_URLS_PER_MSG = 5  # don't fetch a wall of links

_PLAYWRIGHT_AVAILABLE = bool(
    shutil.which("chromium")
    or shutil.which("chromium-browser")
    or shutil.which("chromium-browser-stable")
)


@dataclass
class FetchedPage:
    url: str
    title: str = ""
    content: str = ""
    error: str = ""
    fetched_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))

    @property
    def ok(self) -> bool:
        return bool(self.content) and not self.error

    @property
    def domain(self) -> str:
        try:
            return urlparse(self.url).netloc
        except Exception:
            return self.url

    def to_context(self, max_chars: int = MAX_CONTENT_CHARS) -> str:
        """Format as context block for LLM injection."""
        if self.error:
            return f"[URL: {self.url}]\nError: {self.error}\n"
        content = self.content[:max_chars]
        if len(self.content) > max_chars:
            content += f"\n\n[... truncated at {max_chars} chars ...]"
        title_line = f"Title: {self.title}\n" if self.title else ""
        return f"[URL: {self.url}]\n{title_line}{content}"


def extract_urls(text: str) -> list[str]:
    """Extract all URLs from a text message. Returns unique list, max MAX_URLS_PER_MSG."""
    found = URL_PATTERN.findall(text)
    # Deduplicate preserving order
    seen: set[str] = set()
    unique = []
    for url in found:
        # Clean trailing punctuation that got caught by regex
        url = url.rstrip(".,;:!?")
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique[:MAX_URLS_PER_MSG]


def fetch_url(url: str, use_playwright: bool = False) -> FetchedPage:
    """
    Fetch a URL and extract clean text content.

    Strategy:
      1. Try trafilatura (best for articles/docs)
      2. Fallback to requests + basic HTML strip
      3. Auto playwright when extracted text stays very short (browser on PATH)
      4. Explicit ``use_playwright=True`` for JS-heavy pages
    """
    if use_playwright:
        return _fetch_playwright(url)

    page = _fetch_trafilatura(url)
    if page.ok and len(page.content) >= 200:
        return page

    page2 = _fetch_requests_fallback(url)
    if page2.ok and len(page2.content) >= 200:
        return page2

    if _PLAYWRIGHT_AVAILABLE and len(page2.content) < 200:
        pw_page = _fetch_playwright(url)
        if pw_page.ok:
            return pw_page

    return page2 if page2.ok else page


def fetch_all_urls(urls: list[str], use_playwright: bool = False) -> list[FetchedPage]:
    """Fetch all URLs, returning results in order."""
    pages = []
    for url in urls:
        pages.append(fetch_url(url, use_playwright=use_playwright))
    return pages


def format_pages_for_context(pages: list[FetchedPage]) -> str:
    """Format fetched pages as a single context block for LLM."""
    if not pages:
        return ""
    parts = ["## Web content fetched from URLs in your message:"]
    for page in pages:
        parts.append("")
        parts.append(page.to_context())
    return "\n".join(parts)


# ── Fetchers ──────────────────────────────────────────────────────────────────


def _fetch_trafilatura(url: str) -> FetchedPage:
    try:
        import trafilatura
        from trafilatura.settings import use_config

        # Minimal config: no signal/alarm (works in threads)
        config = use_config()
        config.set("DEFAULT", "EXTRACTION_TIMEOUT", "0")

        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return FetchedPage(url=url, error="Could not download page")

        # Extract main content
        result = trafilatura.extract(
            downloaded,
            config=config,
            include_comments=False,
            include_tables=True,
            no_fallback=False,
            output_format="txt",
        )

        # Extract title separately
        from trafilatura.metadata import extract_metadata

        meta = extract_metadata(downloaded)
        title = meta.title if meta and meta.title else ""

        if not result:
            return FetchedPage(url=url, error="trafilatura: no extractable content")

        return FetchedPage(url=url, title=title, content=result)

    except ImportError:
        return FetchedPage(url=url, error="trafilatura not installed: pip install trafilatura")
    except Exception as e:
        return FetchedPage(url=url, error=f"trafilatura error: {e}")


def _fetch_requests_fallback(url: str) -> FetchedPage:
    """Simple fallback: requests + strip HTML tags."""
    try:
        import requests

        r = requests.get(
            url,
            timeout=FETCH_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0 (compatible; AtmanAgent/1.0)"},
            allow_redirects=True,
        )
        r.raise_for_status()

        content_type = r.headers.get("content-type", "")
        if "text" not in content_type and "json" not in content_type:
            return FetchedPage(url=url, error=f"Non-text content: {content_type}")

        text = r.text

        # Strip HTML tags
        text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"&[a-zA-Z]+;", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

        # Extract title
        title_match = re.search(r"<title[^>]*>(.*?)</title>", r.text, re.IGNORECASE | re.DOTALL)
        title = title_match.group(1).strip() if title_match else ""

        if len(text) < 100:
            return FetchedPage(url=url, error="Page content too short to be useful")

        return FetchedPage(url=url, title=title, content=text[:MAX_CONTENT_CHARS])

    except Exception as e:
        return FetchedPage(url=url, error=f"requests error: {e}")


def _fetch_playwright(url: str) -> FetchedPage:
    """
    JS-aware fetcher using playwright.
    Only used when explicitly requested (heavy dependency).

    Install: pip install playwright && playwright install chromium
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return FetchedPage(
            url=url,
            error="playwright not installed: pip install playwright && playwright install chromium",
        )

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=FETCH_TIMEOUT * 1000, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)  # let JS render

            title = page.title()
            # Extract visible text
            content = page.evaluate("""() => {
                // Remove script/style elements
                document.querySelectorAll('script, style, nav, footer, header').forEach(e => e.remove());
                return document.body.innerText || document.body.textContent || '';
            }""")
            browser.close()

            content = re.sub(r"\s+", " ", content).strip()
            return FetchedPage(url=url, title=title, content=content[:MAX_CONTENT_CHARS])

    except Exception as e:
        return FetchedPage(url=url, error=f"playwright error: {e}")


# ── GitHub-specific helpers ───────────────────────────────────────────────────


def is_github_url(url: str) -> bool:
    return "github.com" in url


def fetch_github_raw(url: str, github_token: str = "") -> FetchedPage:
    """
    Fetch GitHub files/PRs/issues more cleanly via GitHub API.
    Handles:
      - github.com/user/repo/blob/main/file.py → raw content
      - github.com/user/repo/issues/N → issue text
      - github.com/user/repo/pull/N  → PR title + body + diff summary
    """
    import requests

    headers = {"Accept": "application/vnd.github+json"}
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")

    # File blob → raw content
    if len(parts) >= 5 and parts[2] == "blob":
        raw_url = url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
        try:
            r = requests.get(raw_url, timeout=FETCH_TIMEOUT, headers={"User-Agent": "AtmanAgent"})
            r.raise_for_status()
            return FetchedPage(url=url, title=parts[-1], content=r.text[:MAX_CONTENT_CHARS])
        except Exception as e:
            return FetchedPage(url=url, error=str(e))

    # Issue or PR
    if len(parts) >= 4 and parts[2] in ("issues", "pull"):
        repo = f"{parts[0]}/{parts[1]}"
        num = parts[3]
        api_url = f"https://api.github.com/repos/{repo}/{'pulls' if parts[2] == 'pull' else 'issues'}/{num}"
        try:
            r = requests.get(api_url, headers=headers, timeout=FETCH_TIMEOUT)
            r.raise_for_status()
            data = r.json()
            content = f"Title: {data.get('title', '')}\n\n{data.get('body', '')}"
            return FetchedPage(url=url, title=data.get("title", ""), content=content)
        except Exception as e:
            return FetchedPage(url=url, error=str(e))

    # Fallback
    return fetch_url(url)
