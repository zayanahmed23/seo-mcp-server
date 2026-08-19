"""
FastMCP Server Configuration.
Registers the Crawler, GSC, and GA4 wrappers as strongly-typed tools for LLM consumption.
"""

import json
import logging
import re
from typing import List, Optional
from mcp.server.fastmcp import FastMCP

# Use the clean namespace imports defined in your __init__.py files
from src.crawler import crawl_site
from src.api import gsc_client, ga4_client

# stdout is reserved for the MCP stdio transport; route logs to stderr so
# they never corrupt protocol framing (this is FastMCP/logging's default,
# made explicit here since we rely on it for error redaction below).
logger = logging.getLogger(__name__)

# Matches Windows drive-letter paths (C:\Users\name\...) and POSIX home
# paths (/home/name/..., /Users/name/...) so they can be stripped out of
# error text before it's handed back to the calling LLM/client. Exception
# messages from libraries we call (e.g. FileNotFoundError) can otherwise
# embed the local username or full directory layout. Quoted alternatives
# are matched first since path segments (e.g. "SEO MCP server") may
# contain spaces, which would otherwise truncate the bare-path match.
_PATH_PATTERN = re.compile(
    r"'[A-Za-z]:\\[^']*'"
    r'|"[A-Za-z]:\\[^"]*"'
    r"|[A-Za-z]:\\[^\s\"']+"
    r"|'/(?:home|Users)/[^']*'"
    r'|"/(?:home|Users)/[^"]*"'
    r"|/(?:home|Users)/[^\s\"']+"
)


def _redact_path(match: re.Match) -> str:
    text = match.group(0)
    if text[0] in "'\"":
        return f"{text[0]}<path>{text[0]}"
    return "<path>"


def _sanitize_error(exc: Exception, context: str) -> str:
    """
    Logs the full exception (with traceback) locally for debugging, and
    returns a short, redacted message safe to send back through the MCP
    tool response - which may be relayed to a third-party hosted LLM.
    """
    logger.exception(context)
    message = _PATH_PATTERN.sub(_redact_path, str(exc))
    return f"{context}: {type(exc).__name__}: {message}"


# Initialize the FastMCP Server
mcp = FastMCP("SEO_Systems_Architect")


@mcp.tool()
async def audit_site_structure(start_url: str, path_prefix: str = "/") -> str:
    """
    Crawls a target website to extract technical SEO metadata, H1s, and clean text.
    Respects strict token limits by writing raw HTML to disk and returning a truncated JSON manifest.
    
    Args:
        start_url: The entry point URL for the crawl (e.g., 'https://example.com/').
        path_prefix: Restricts the crawl to specific subdirectories (defaults to '/').
    """
    try:
        # The crawler is I/O bound and utilizes Playwright, so it must be awaited
        result = await crawl_site(start_url, path_prefix)
        
        # Ensure the result is always a string to prevent transport layer serialization errors
        return result if isinstance(result, str) else json.dumps(result)
    except Exception as e:
        # Graceful degradation: Return the error to the LLM so it can attempt a self-correction
        return json.dumps({"error": _sanitize_error(e, "Crawler failed to execute")})


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
        start_date: The beginning of the date range in YYYY-MM-DD format.
        end_date: The end of the date range in YYYY-MM-DD format.
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
        return json.dumps(result, indent=2)
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
        start_date: Start date in YYYY-MM-DD format, or relative formats like '30daysAgo'.
        end_date: End date in YYYY-MM-DD format, or 'today'.
        dimensions: List of dimensions to group by. Defaults to ['sessionDefaultChannelGroup'].
    """
    try:
        result = ga4_client.query_performance_data(
            property_id=property_id, 
            start_date=start_date, 
            end_date=end_date, 
            dimensions=dimensions
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": _sanitize_error(e, "GA4 API query failed")})