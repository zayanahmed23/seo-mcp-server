"""
Shared error-text redaction.

Tool responses cross the MCP boundary and may be relayed to a third-party
hosted LLM, so local filesystem paths (which embed the OS username and
directory layout) must be stripped first. This lives in its own module
because both the raised-exception path in src.server and the caught-and-
returned {"error": ...} dicts in the API clients need the same treatment -
an earlier version only covered the former, so client errors leaked paths.
"""

from __future__ import annotations

import re

# Matches Windows drive-letter paths (C:\Users\name\...) and POSIX home
# paths (/home/name/..., /Users/name/...). Quoted alternatives are listed
# first because path segments may contain spaces (e.g. "SEO MCP server"),
# which would otherwise truncate the bare-path match at the space.
_PATH_PATTERN = re.compile(
    r"'[A-Za-z]:\\[^']*'"
    r'|"[A-Za-z]:\\[^"]*"'
    r"|[A-Za-z]:\\[^\s\"']+"
    r"|'/(?:home|Users)/[^']*'"
    r'|"/(?:home|Users)/[^"]*"'
    r"|/(?:home|Users)/[^\s\"']+"
)


def _replace(match: re.Match) -> str:
    text = match.group(0)
    if text[0] in "'\"":
        return f"{text[0]}<path>{text[0]}"
    return "<path>"


def redact_paths(text: str) -> str:
    """Replaces local filesystem paths in `text` with '<path>'."""
    return _PATH_PATTERN.sub(_replace, text)
