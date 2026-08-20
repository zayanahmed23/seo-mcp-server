"""
Convenience entry point for running straight from a clone.

Keeps `python main.py` working without installing the package. Installed
users get the `seo-mcp-server` console script or `python -m seo_mcp_server`
instead; both call the same function.
"""

import sys
from pathlib import Path

# Put this directory on sys.path so `seo_mcp_server` imports resolve no matter
# which working directory the MCP client spawns us from.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from seo_mcp_server.cli import main

if __name__ == "__main__":
    main()
