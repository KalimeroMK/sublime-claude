"""DuckDuckGo web search — no API key required."""
import re
import ssl
import urllib.request
import urllib.parse
from typing import List, Dict


def _fetch_html(url: str, timeout: int = 10) -> str:
    """Fetch URL with minimal headers."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _parse_lite_results(html: str) -> List[Dict[str, str]]:
    """Parse DuckDuckGo Lite HTML into result dicts."""
    results = []
    # Each result is a table row with class "result-link" or similar
    # Links: <a rel="nofollow" class="result-link" href="...">title</a>
    # Snippets: <td class="result-snippet">...</td>
    link_pattern = re.compile(
        r'<a[^>]+class="result-link"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    snippet_pattern = re.compile(
        r'<td[^>]+class="result-snippet"[^>]*>(.*?)</td>',
        re.IGNORECASE | re.DOTALL,
    )

    links = link_pattern.findall(html)
    snippets = snippet_pattern.findall(html)

    for i, (href, title) in enumerate(links):
        # Clean title — strip tags
        title = re.sub(r'<[^>]+>', '', title).strip()
        # Clean href — DuckDuckGo redirects through /l/?...
        if href.startswith("/"):
            # Skip internal links
            continue
        snippet = ""
        if i < len(snippets):
            snippet = re.sub(r'<[^>]+>', '', snippets[i]).strip()
        if title and href:
            results.append({"title": title, "url": href, "snippet": snippet})
        if len(results) >= 5:
            break

    return results


def _parse_html_results(html: str) -> List[Dict[str, str]]:
    """Parse DuckDuckGo HTML (non-lite) into result dicts."""
    results = []
    # Find all result__a links and pair with nearest result__snippet
    link_pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    snippet_pattern = re.compile(
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )

    links = link_pattern.findall(html)
    snippets = snippet_pattern.findall(html)

    for i, (href, title) in enumerate(links):
        title = re.sub(r'<[^>]+>', '', title).strip()
        # Skip ads / internal links
        if href.startswith("/") or "duckduckgo.com" in href:
            continue
        snippet = ""
        if i < len(snippets):
            snippet = re.sub(r'<[^>]+>', '', snippets[i]).strip()
        if title and href:
            results.append({"title": title, "url": href, "snippet": snippet})
        if len(results) >= 5:
            break

    return results


def search(query: str, top_k: int = 5) -> List[Dict[str, str]]:
    """Search DuckDuckGo and return top results.

    Args:
        query: Search query string
        top_k: Number of results to return (default 5)

    Returns:
        List of dicts with keys: title, url, snippet
    """
    encoded = urllib.parse.quote(query)
    # Try lite version first (simpler HTML)
    urls = [
        f"https://lite.duckduckgo.com/lite/?q={encoded}",
        f"https://html.duckduckgo.com/html/?q={encoded}",
    ]
    for url in urls:
        try:
            html = _fetch_html(url)
            if "lite.duckduckgo.com" in url:
                results = _parse_lite_results(html)
            else:
                results = _parse_html_results(html)
            if results:
                return results[:top_k]
        except Exception as e:
            print(f"[Claude] DuckDuckGo search error ({url}): {e}")
            continue
    return []
