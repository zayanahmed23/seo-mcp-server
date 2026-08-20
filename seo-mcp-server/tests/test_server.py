"""Tool registration, error redaction, and fail-fast validation."""

import json

import pytest

from seo_mcp_server.errors import redact_paths
from seo_mcp_server.server import _sanitize_error, _sanitize_result, mcp

EXPECTED_TOOLS = {
    "audit_site_structure",
    "list_verified_sites",
    "get_gsc_performance",
    "get_ga4_metrics",
}


async def test_all_tools_are_registered():
    assert {t.name for t in await mcp.list_tools()} == EXPECTED_TOOLS


async def test_every_tool_documents_itself():
    """The docstring is the interface the model reads."""
    for tool in await mcp.list_tools():
        assert tool.description and len(tool.description.strip()) > 40, tool.name


class TestPathRedaction:
    @pytest.mark.parametrize(
        "text,leak",
        [
            (r"Missing file at 'C:\Users\Zayan\Projects\SEO MCP server\secret.json'.", "Zayan"),
            (r"bare path C:\Users\zayan\noquotes.json failed", "zayan"),
            ("unix /Users/zayan/secret/file.txt missing", "zayan"),
            ('quoted "/home/zayan/app data/token.json" missing', "zayan"),
        ],
    )
    def test_local_paths_are_stripped(self, text, leak):
        out = redact_paths(text)
        assert leak not in out
        assert "<path>" in out

    def test_quotes_are_preserved_around_redactions(self):
        assert redact_paths(r"at 'C:\Users\x\a.json'.") == "at '<path>'."

    def test_windows_paths_with_spaces_are_fully_stripped(self):
        """A space used to terminate the match, leaking the tail."""
        out = redact_paths(r"'C:\Users\Zayan\SEO MCP server\client_secret.json'")
        assert "MCP server" not in out

    def test_non_path_text_is_untouched(self):
        msg = "Quota exceeded for property 123456789"
        assert redact_paths(msg) == msg


class TestErrorSanitizing:
    def test_exception_type_is_kept_for_debuggability(self):
        out = _sanitize_error(ValueError("bad thing"), "Widget failed")
        assert "Widget failed" in out and "ValueError" in out and "bad thing" in out

    def test_paths_are_redacted_from_raised_exceptions(self):
        exc = FileNotFoundError(r"missing 'C:\Users\zayan\client_secret.json'")
        assert "zayan" not in _sanitize_error(exc, "ctx")

    def test_returned_error_dicts_are_redacted(self):
        """API clients return error dicts rather than raising, which used to
        bypass redaction entirely."""
        payload = {"error": r"Failed: missing 'C:\Users\zayan\token.json'"}
        assert "zayan" not in _sanitize_result(payload)["error"]

    def test_successful_results_pass_through_unchanged(self):
        payload = {"rows_returned": 3, "data": [{"clicks": 1}]}
        assert _sanitize_result(payload) == payload

    def test_non_dict_results_are_untouched(self):
        assert _sanitize_result("plain string") == "plain string"


class TestFailFastValidation:
    """Bad dates must be rejected before any network or OAuth work - otherwise
    a typo triggers a browser consent prompt."""

    @pytest.mark.parametrize(
        "tool,args",
        [
            ("get_gsc_performance",
             {"site_url": "https://example.com/", "start_date": "garbage", "end_date": "today"}),
            ("get_ga4_metrics",
             {"property_id": "123456789", "start_date": "2026-13-01", "end_date": "today"}),
            ("get_gsc_performance",
             {"site_url": "https://example.com/", "start_date": "today", "end_date": "30daysAgo"}),
        ],
    )
    async def test_bad_dates_error_without_touching_credentials(self, tool, args):
        result = await mcp.call_tool(tool, args)
        payload = json.loads(result[0][0].text)
        assert "error" in payload
        # An auth attempt would name the credential file instead.
        assert "client secret" not in payload["error"].lower()


class TestCrawlerToolGuards:
    async def test_internal_targets_are_refused_through_the_tool(self):
        result = await mcp.call_tool(
            "audit_site_structure",
            {"start_url": "http://169.254.169.254/latest/meta-data/", "path_prefix": "/"},
        )
        payload = json.loads(result[0][0].text)
        assert "error" in payload
        assert "internal" in payload["error"].lower() or "refus" in payload["error"].lower()

    async def test_non_http_scheme_is_refused_through_the_tool(self):
        result = await mcp.call_tool(
            "audit_site_structure",
            {"start_url": "file:///etc/passwd", "path_prefix": "/"},
        )
        assert "error" in json.loads(result[0][0].text)
