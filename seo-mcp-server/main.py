"""
MCP Server Entry Point.
Executes the FastMCP server over standard input/output (stdio) for local AI clients.
"""

from src.server import mcp

def main():
    """Boots the FastMCP server using the default stdio transport."""
    # FastMCP automatically handles the async event loop and thread pooling
    mcp.run()

if __name__ == "__main__":
    main()