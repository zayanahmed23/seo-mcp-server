"""
FastMCP Server Configuration.
Registers the Crawler, GSC, and GA4 wrappers as strongly-typed tools for LLM consumption.
"""

import json
import logging
from typing import List, Optional
from mcp.server.fastmcp import FastMCP

# Use the clean namespace imports defined in your __init__.py files
from src.crawler import crawl_site
from src.api import gsc_client, ga4_client
from src.errors import redact_paths

# stdout is reserved for the MCP stdio transport; route logs to stderr so
# they never corrupt protocol framing (this is FastMCP/logging's default,
# made explicit here since we rely on it for error redaction below).
logger = logging.getLogger(__name__)

def _sanitize_error(exc: Exception, context: str) -> str:
    """
    Logs the full exception (with traceback) locally for debugging, and
    returns a short, redacted message safe to send back through the MCP
    tool response - which may be relayed to a third-party hosted LLM.
    """
    logger.exception(context)
    return f"{context}: {type(exc).__name__}: {redact_paths(str(exc))}"


def _sanitize_result(result: dict) -> dict:
    """
    Redacts paths from an {"error": ...} dict returned (not raised) by an
    API client. These bypass _sanitize_error entirely, so without this the
    client's own error strings would still leak local paths.
    """
    if isinstance(result, dict) and isinstance(result.get("error"), str):
        return {**result, "error": redact_paths(result["error"])}
    return result


# Initialize the FastMCP Server
mcp = FastMCP("SEO_Systems_Architect")


@mcp.tool()
async def audit_site_structure(
    start_url: str,
    path_prefix: str = "/",
    respect_robots: bool = True,
) -> str:
    """
    Crawls a target website to extract technical SEO metadata, H1s, and clean text.
    Respects strict token limits by writing raw HTML to disk and returning a truncated JSON manifest.

    Args:
        start_url: The entry point URL for the crawl (e.g., 'https://example.com/').
        path_prefix: Restricts the crawl to specific subdirectories (defaults to '/').
        respect_robots: Honour the site's robots.txt (default true). Set false only
            when the user confirms they own the site and want to override it.
    """
    try:
        # The crawler is I/O bound and utilizes Playwright, so it must be awaited
        result = await crawl_site(start_url, path_prefix, respect_robots=respect_robots)
        
        # Ensure the result is always a string to prevent transport layer serialization errors
        if isinstance(result, str):
            return result
        return json.dumps(_sanitize_result(result))
    except Exception as e:
        # Graceful degradation: Return the error to the LLM so it can attempt a self-correction
        return json.dumps({"error": _sanitize_error(e, "Crawler failed to execute")})


@mcp.tool()
def list_verified_sites() -> str:
    """
    Lists the Search Console properties this Google account can access.

    Call this first when the user hasn't given an exact site_url - GSC requires
    the property string to match exactly (e.g. 'https://www.example.com/' and
    'sc-domain:example.com' are different properties).
    """
    try:
        sites = gsc_client.get_verified_sites()
        return json.dumps({"sites": sites, "count": len(sites)}, indent=2)
    except Exception as e:
        return json.dumps({"error": _sanitize_error(e, "Could not list verified sites")})


@mcp.tool()
def get_gsc_performance(
    site_url: str, 
    start_date: str, 
    end_date: str, 
    dimensions: Optional[List[str]] = None
) -> str:
    """
    Queries Google Search Console for organic performance metrics (clicks, impressions, CTR, position).
    
    Args:
        site_url: The exact property URL verified in GSC (e.g., 'https://www.example.com/').
        start_date: Beginning of the range. Accepts 'YYYY-MM-DD', a whole month
            as 'YYYY-MM', or relative forms: 'today', 'yesterday', 'NdaysAgo'
            (e.g. '30daysAgo'), 'lastNdays' (e.g. 'last7days'), 'thisMonth',
            'lastMonth', 'thisYear', 'lastYear'.
        end_date: End of the range, same accepted formats. Period tokens resolve
            to the period's LAST day here, so passing 'lastMonth' for both
            start_date and end_date covers that entire month.
        dimensions: List of dimensions to group by (e.g., ['query', 'page', 'device']). Defaults to ['query', 'page'].
    """
    try:
        # FastMCP automatically runs synchronous functions in a threadpool to avoid blocking the event loop
        result = gsc_client.query_search_analytics(
            site_url=site_url,
            start_date=start_date,
            end_date=end_date,
            dimensions=dimensions
        )
        return json.dumps(_sanitize_result(result), indent=2)
    except Exception as e:
        return json.dumps({"error": _sanitize_error(e, "GSC API query failed")})


@mcp.tool()
def get_ga4_metrics(
    property_id: str, 
    start_date: str, 
    end_date: str, 
    dimensions: Optional[List[str]] = None
) -> str:
    """
    Queries Google Analytics 4 for traffic, engagement, and conversion metrics.
    
    Args:
        property_id: The GA4 Property ID (e.g., '123456789').
        start_date: Beginning of the range. Accepts 'YYYY-MM-DD', a whole month
            as 'YYYY-MM', or relative forms: 'today', 'yesterday', 'NdaysAgo'
            (e.g. '30daysAgo'), 'lastNdays' (e.g. 'last7days'), 'thisMonth',
            'lastMonth', 'thisYear', 'lastYear'.
        end_date: End of the range, same accepted formats. Period tokens resolve
            to the period's LAST day here, so passing 'lastMonth' for both
            start_date and end_date covers that entire month.
        dimensions: List of dimensions to group by. Defaults to ['sessionDefaultChannelGroup'].
    """
    try:
        result = ga4_client.query_performance_data(
            property_id=property_id,
            start_date=start_date,
            end_date=end_date,
            dimensions=dimensions
        )
        return json.dumps(_sanitize_result(result), indent=2)
    except Exception as e:
        return json.dumps({"error": _sanitize_error(e, "GA4 API query failed")})