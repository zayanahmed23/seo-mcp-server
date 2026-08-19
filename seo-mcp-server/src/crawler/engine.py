"""
Headless Playwright SEO crawling engine.

Crawls a site starting at a given URL, restricted to a path prefix, and
extracts technical SEO metadata (title, meta description, robots directives,
canonical URL, H1s, clean text) for each page. Raw HTML is written to disk
per page and the function returns a compact JSON-serializable manifest so
callers (e.g. an LLM tool caller) don't get flooded with full page markup.

SSRF hardening: the crawler is driven by a `start_url` argument that may
ultimately be supplied by an LLM (which can itself be steered by content it
has read elsewhere - classic prompt injection). To stop it being used to
reach internal/private network services, every URL is validated for scheme
and resolved-IP safety before Playwright is allowed to request it, both up
front and via a per-request route guard inside the browser context (which
also covers redirects and subresource requests like images/scripts).
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Route, async_playwright

ALLOWED_SCHEMES = {"http", "https"}
MAX_PAGES = 20
MAX_DEPTH = 3
NAV_TIMEOUT_MS = 15_000
TEXT_PREVIEW_CHARS = 1500
OUTPUT_DIR = Path("crawl_output")


def _is_disallowed_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True if this address points at a private/internal/reserved network."""
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _check_url_is_safe(url: str) -> Tuple[bool, str]:
    """
    Validates scheme and resolves the hostname to block SSRF targets
    (loopback, RFC1918/private ranges, link-local incl. the 169.254.169.254
    cloud metadata endpoint, multicast, and other reserved ranges).

    Note: this is a DNS-resolution-time check, not a connection-time pin, so
    it cannot fully defeat a DNS-rebinding attacker who reanswers the same
    hostname differently between check and connect. The per-request route
    guard registered on the browser context re-runs this check immediately
    before every navigation and subresource request, which shrinks that
    window to as small as Playwright allows.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        return False, f"Disallowed URL scheme '{parsed.scheme}'; only http/https are permitted."

    hostname = parsed.hostname
    if not hostname:
        return False, "URL is missing a hostname."

    if hostname.lower() == "localhost":
        return False, "Refusing to crawl 'localhost'."

    try:
        resolved = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        return False, f"DNS resolution failed for '{hostname}': {exc}"

    for info in resolved:
        raw_ip = info[4][0]
        ip = ipaddress.ip_address(raw_ip.split("%")[0])
        if _is_disallowed_ip(ip):
            return False, f"Refusing to crawl internal/reserved address '{raw_ip}' for host '{hostname}'."

    return True, ""


async def _route_guard(route: Route) -> None:
    """Per-request defense-in-depth: re-validates every navigation and
    subresource request the browser context makes, including redirects."""
    safe, _reason = _check_url_is_safe(route.request.url)
    if safe:
        await route.continue_()
    else:
        await route.abort("blockedbyclient")


def _normalize(url: str) -> str:
    """Strips fragments so '#section' variants of the same page dedupe."""
    parsed = urlparse(url)
    return urlunparse(parsed._replace(fragment=""))


def _safe_html_path(url: str) -> Path:
    """Derives a filesystem path for the raw HTML dump that can never escape
    OUTPUT_DIR, regardless of what the crawled URL's path/query contain."""
    parsed = urlparse(url)
    domain_dir = re.sub(r"[^A-Za-z0-9_.-]", "_", parsed.netloc) or "unknown_host"
    filename = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16] + ".html"
    return OUTPUT_DIR / domain_dir / filename


def _extract_metadata(url: str, status: int | None, html: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")

    title = soup.title.get_text(strip=True) if soup.title else None

    meta_desc_tag = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    meta_description = meta_desc_tag.get("content", "").strip() if meta_desc_tag else None

    meta_robots_tag = soup.find("meta", attrs={"name": re.compile("^robots$", re.I)})
    meta_robots = meta_robots_tag.get("content", "").strip() if meta_robots_tag else None

    canonical_tag = soup.find("link", attrs={"rel": re.compile("^canonical$", re.I)})
    canonical = canonical_tag.get("href", "").strip() if canonical_tag else None

    h1s = [h.get_text(strip=True) for h in soup.find_all("h1")]

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    clean_text = re.sub(r"\s+", " ", soup.get_text(separator=" ")).strip()

    return {
        "url": url,
        "status": status,
        "title": title,
        "meta_description": meta_description,
        "meta_robots": meta_robots,
        "canonical": canonical,
        "h1": h1s,
        "word_count": len(clean_text.split()) if clean_text else 0,
        "text_preview": clean_text[:TEXT_PREVIEW_CHARS],
    }


def _extract_links(base_url: str, html: str, origin: str, path_prefix: str) -> List[str]:
    soup = BeautifulSoup(html, "lxml")
    links: List[str] = []
    for a_tag in soup.find_all("a", href=True):
        resolved = _normalize(urljoin(base_url, a_tag["href"]))
        parsed = urlparse(resolved)
        if parsed.scheme not in ALLOWED_SCHEMES:
            continue
        if parsed.netloc != origin:
            continue
        if not parsed.path.startswith(path_prefix):
            continue
        links.append(resolved)
    return links


async def crawl_site(start_url: str, path_prefix: str = "/") -> Dict[str, Any]:
    """
    Crawls a site breadth-first starting at `start_url`, following only
    same-origin links whose path starts with `path_prefix`, up to MAX_PAGES
    pages and MAX_DEPTH link hops. Writes raw HTML for each page to disk
    under ./crawl_output/ and returns a truncated JSON-friendly manifest.
    """
    safe, reason = _check_url_is_safe(start_url)
    if not safe:
        return {"error": reason, "start_url": start_url}

    start_parsed = urlparse(start_url)
    origin = start_parsed.netloc

    visited: Set[str] = set()
    queue: List[Tuple[str, int]] = [(_normalize(start_url), 0)]
    pages: List[Dict[str, Any]] = []
    blocked: List[Dict[str, str]] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            context = await browser.new_context()
            await context.route("**/*", _route_guard)
            page = await context.new_page()

            while queue and len(pages) < MAX_PAGES:
                url, depth = queue.pop(0)
                if url in visited:
                    continue
                visited.add(url)

                page_safe, page_reason = _check_url_is_safe(url)
                if not page_safe:
                    blocked.append({"url": url, "reason": page_reason})
                    continue

                try:
                    response = await page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
                except PlaywrightError as exc:
                    pages.append({"url": url, "error": f"Navigation failed: {exc}"})
                    continue

                html = await page.content()
                status = response.status if response else None

                metadata = _extract_metadata(url, status, html)

                html_path = _safe_html_path(url)
                html_path.parent.mkdir(parents=True, exist_ok=True)
                html_path.write_text(html, encoding="utf-8")
                metadata["raw_html_path"] = str(html_path)

                pages.append(metadata)

                if depth < MAX_DEPTH:
                    for link in _extract_links(url, html, origin, path_prefix):
                        if link not in visited:
                            queue.append((link, depth + 1))
        finally:
            await browser.close()

    return {
        "start_url": start_url,
        "path_prefix": path_prefix,
        "pages_crawled": len(pages),
        "pages_remaining_in_queue": len(queue),
        "truncated": bool(queue),
        "max_pages_limit": MAX_PAGES,
        "max_depth_limit": MAX_DEPTH,
        "blocked_urls": blocked,
        "pages": pages,
    }
