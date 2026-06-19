"""Optional web tools -- OFF by default.

The running agent has no network egress except through these tools, and only
when ``web.enabled: true`` in the config. Even then, every request is gated:

* scheme must be http/https,
* the host must be on ``web.allowed_hosts`` (when that list is non-empty),
* responses are capped at ``web.max_bytes``.

When web access is disabled (the default) every call returns a clear failure
without touching the network.
"""

from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
from typing import Any, Tuple

from .base import Tool, ToolResult


def _web_cfg(config: Any) -> Any:
    return getattr(config, "web", None)


def _guard(config: Any, url: str) -> Tuple[bool, str]:
    """Return (allowed, reason). Reason is empty when allowed."""
    web = _web_cfg(config)
    if not web or not getattr(web, "enabled", False):
        return False, "web access is disabled (set web.enabled: true to allow it)"
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False, f"unsupported URL scheme: {parsed.scheme or '(none)'}"
    allowed_hosts = list(getattr(web, "allowed_hosts", []) or [])
    if allowed_hosts and parsed.hostname not in allowed_hosts:
        return False, f"host {parsed.hostname!r} is not in web.allowed_hosts"
    return True, ""


def _fetch(config: Any, url: str) -> Tuple[str, int]:
    web = _web_cfg(config)
    max_bytes = int(getattr(web, "max_bytes", 1_000_000))
    timeout = int(getattr(web, "fetch_timeout", 20))
    req = urllib.request.Request(url, headers={"User-Agent": "self-improving-agent/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(max_bytes + 1)
    truncated = len(raw) > max_bytes
    text = raw[:max_bytes].decode("utf-8", errors="replace")
    return text, (1 if truncated else 0)


_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


class WebFetchTool(Tool):
    name = "web_fetch"
    description = "Fetch a URL and return its text (HTML stripped). Disabled by default."
    parameters = {"url": "The http(s) URL to fetch."}

    def run(self, *, url: str, **_: Any) -> ToolResult:
        ok, reason = _guard(self.context.config, url)
        if not ok:
            return ToolResult.failure(reason)
        try:
            text, truncated = _fetch(self.context.config, url)
        except Exception as exc:  # network/HTTP errors are expected failures
            return ToolResult.failure(f"fetch failed: {exc}")
        return ToolResult.success(_strip_html(text), url=url, truncated=bool(truncated))


class WebSearchTool(Tool):
    name = "web_search"
    description = (
        "Search the web (DuckDuckGo HTML) and return result titles + links. "
        "Disabled by default."
    )
    parameters = {"query": "The search query."}

    SEARCH_URL = "https://duckduckgo.com/html/?q={q}"

    def run(self, *, query: str, **_: Any) -> ToolResult:
        url = self.SEARCH_URL.format(q=urllib.parse.quote(query))
        ok, reason = _guard(self.context.config, url)
        if not ok:
            return ToolResult.failure(reason)
        try:
            html_text, _ = _fetch(self.context.config, url)
        except Exception as exc:
            return ToolResult.failure(f"search failed: {exc}")
        results = re.findall(
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            html_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not results:
            return ToolResult.success("(no results parsed)", query=query)
        lines = [f"- {_strip_html(title)} :: {link}" for link, title in results[:10]]
        return ToolResult.success("\n".join(lines), query=query, count=len(lines))
