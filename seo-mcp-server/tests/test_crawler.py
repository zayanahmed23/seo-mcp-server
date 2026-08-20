"""SSRF guards, filesystem safety, and HTML extraction.

These run offline: every URL uses a numeric address or a short-circuiting
hostname, so no DNS is needed. Tests that touch the network are marked.
"""

import pytest

from seo_mcp_server.crawler.engine import (
    OUTPUT_DIR,
    _check_url_is_safe,
    _extract_links,
    _extract_metadata,
    _normalize,
    _robots_allows,
    _safe_html_path,
)


class TestSSRFGuards:
    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/",
            "http://127.0.0.1:8080/admin",
            "https://127.0.0.1/",
            "http://10.0.0.5/",
            "http://192.168.1.1/",
            "http://172.16.0.1/",
            "http://169.254.169.254/latest/meta-data/",  # cloud metadata
            "http://0.0.0.0/",
            "http://[::1]/",
            "http://[::ffff:127.0.0.1]/",       # IPv4-mapped loopback
            "http://[::ffff:169.254.169.254]/",  # IPv4-mapped metadata
            "http://[fd00::1]/",                 # unique local
            "http://localhost/",
            "http://LOCALHOST/",
        ],
    )
    def test_internal_targets_are_refused(self, url):
        safe, reason = _check_url_is_safe(url)
        assert safe is False
        assert reason

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "ftp://example.com/",
            "gopher://example.com/",
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
        ],
    )
    def test_non_http_schemes_are_refused(self, url):
        safe, reason = _check_url_is_safe(url)
        assert safe is False
        assert "scheme" in reason.lower() or "hostname" in reason.lower()

    def test_missing_hostname_is_refused(self):
        safe, _ = _check_url_is_safe("http:///nohost")
        assert safe is False

    def test_unresolvable_host_is_refused(self):
        safe, reason = _check_url_is_safe("http://this-host-does-not-exist.invalid/")
        assert safe is False
        assert "resolution" in reason.lower() or "refus" in reason.lower()

    @pytest.mark.network
    def test_public_host_is_allowed(self):
        safe, reason = _check_url_is_safe("https://example.com/")
        assert safe is True, reason


class TestFilesystemSafety:
    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/../../etc/passwd",
            "https://example.com/%2e%2e%2f%2e%2e%2fetc/passwd",
            "https://example.com/a?x=../../../../secret",
            "https://exa mple.com/weird",
        ],
    )
    def test_crawled_urls_cannot_escape_the_output_dir(self, url):
        path = _safe_html_path(url)
        resolved = path.resolve()
        assert OUTPUT_DIR.resolve() in resolved.parents

    def test_filename_is_a_hash_not_the_url(self):
        path = _safe_html_path("https://example.com/some/deep/path?q=1")
        assert path.suffix == ".html"
        assert "path" not in path.stem
        assert len(path.stem) == 16

    def test_distinct_urls_get_distinct_files(self):
        a = _safe_html_path("https://example.com/one")
        b = _safe_html_path("https://example.com/two")
        assert a != b

    def test_same_url_is_stable(self):
        u = "https://example.com/one"
        assert _safe_html_path(u) == _safe_html_path(u)


class TestNormalize:
    def test_fragment_is_stripped(self):
        assert _normalize("https://e.com/a#top") == "https://e.com/a"

    def test_query_is_preserved(self):
        assert _normalize("https://e.com/a?b=1#top") == "https://e.com/a?b=1"


class TestLinkExtraction:
    HTML = """
      <a href="/blog/one">1</a>
      <a href="/blog/two#x">2</a>
      <a href="/about">3</a>
      <a href="https://other.com/blog/x">4</a>
      <a href="mailto:hi@e.com">5</a>
      <a href="javascript:void(0)">6</a>
      <a href="https://e.com/blog/three">7</a>
    """

    def test_only_same_origin_under_prefix(self):
        links = _extract_links("https://e.com/", self.HTML, "e.com", "/blog")
        assert "https://e.com/blog/one" in links
        assert "https://e.com/blog/three" in links

    def test_offsite_and_non_http_are_dropped(self):
        links = _extract_links("https://e.com/", self.HTML, "e.com", "/")
        assert not any("other.com" in l for l in links)
        assert not any(l.startswith(("mailto:", "javascript:")) for l in links)

    def test_prefix_excludes_siblings(self):
        links = _extract_links("https://e.com/", self.HTML, "e.com", "/blog")
        assert not any(l.endswith("/about") for l in links)

    def test_fragments_are_normalized_away(self):
        links = _extract_links("https://e.com/", self.HTML, "e.com", "/blog")
        assert "https://e.com/blog/two" in links


class TestMetadataExtraction:
    HTML = """
      <html><head>
        <title>  Page Title </title>
        <meta name="description" content="A description.">
        <meta name="ROBOTS" content="noindex, follow">
        <link rel="canonical" href="https://e.com/canonical">
      </head><body>
        <h1>First</h1><h1>Second</h1>
        <script>var hidden = "js";</script>
        <style>.x{color:red}</style>
        <p>Visible words here.</p>
      </body></html>
    """

    @pytest.fixture
    def meta(self):
        return _extract_metadata("https://e.com/p", 200, self.HTML)

    def test_core_fields(self, meta):
        assert meta["title"] == "Page Title"
        assert meta["meta_description"] == "A description."
        assert meta["canonical"] == "https://e.com/canonical"
        assert meta["status"] == 200

    def test_case_insensitive_attribute_match(self, meta):
        assert meta["meta_robots"] == "noindex, follow"

    def test_all_h1s_collected(self, meta):
        assert meta["h1"] == ["First", "Second"]

    def test_script_and_style_excluded_from_text(self, meta):
        assert "hidden" not in meta["text_preview"]
        assert "color:red" not in meta["text_preview"]
        assert "Visible words here." in meta["text_preview"]

    def test_missing_fields_are_none_not_crashes(self):
        m = _extract_metadata("https://e.com/", 404, "<html><body>x</body></html>")
        assert m["title"] is None
        assert m["meta_description"] is None
        assert m["canonical"] is None
        assert m["h1"] == []

    def test_empty_html_is_survivable(self):
        m = _extract_metadata("https://e.com/", None, "")
        assert m["word_count"] == 0


def test_robots_allows_when_no_parser():
    """A missing robots.txt means unrestricted, per the standard."""
    assert _robots_allows(None, "https://e.com/anything") is True
