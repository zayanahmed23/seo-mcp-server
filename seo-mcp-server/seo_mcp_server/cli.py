"""
Command line entry point.

Runs the FastMCP server over stdio for local AI clients, or performs a
setup check with `--check`.
"""

import json
import sys
from pathlib import Path


def _check() -> int:
    """Prints a setup report and returns a process exit code."""
    ok = True

    def line(good, label, detail=""):
        nonlocal ok
        if not good:
            ok = False
        mark = "OK  " if good else "FAIL"
        print(f"  [{mark}] {label}" + (f"  -> {detail}" if detail else ""))

    print("\nseo-mcp-server setup check\n" + "-" * 46)

    print("\nRuntime")
    v = sys.version_info
    line(v >= (3, 10), f"Python {v.major}.{v.minor}.{v.micro}",
         "" if v >= (3, 10) else "Python 3.10+ required")

    print("\nDependencies")
    for mod, label in [
        ("mcp.server.fastmcp", "mcp (FastMCP)"),
        ("playwright.async_api", "playwright"),
        ("bs4", "beautifulsoup4"),
        ("lxml", "lxml"),
        ("googleapiclient.discovery", "google-api-python-client"),
        ("google.analytics.data_v1beta", "google-analytics-data"),
        ("google_auth_oauthlib.flow", "google-auth-oauthlib"),
    ]:
        try:
            __import__(mod)
            line(True, label)
        except Exception as exc:
            line(False, label, f"{type(exc).__name__}: pip install -r requirements.txt")

    print("\nBrowser")
    # Run in a subprocess: Playwright's driver teardown otherwise races with
    # the asyncio loop used further down and prints shutdown noise.
    import subprocess
    probe = (
        "from playwright.sync_api import sync_playwright;"
        "import pathlib;"
        "p=sync_playwright().start();"
        "print(p.chromium.executable_path);"
        "p.stop()"
    )
    try:
        res = subprocess.run([sys.executable, "-c", probe],
                             capture_output=True, text=True, timeout=60)
        exe = Path(res.stdout.strip()) if res.returncode == 0 and res.stdout.strip() else None
        line(bool(exe and exe.exists()), "Chromium for Playwright",
             str(exe) if exe and exe.exists() else "run: python -m playwright install chromium")
    except Exception:
        line(False, "Chromium for Playwright",
             "run: python -m playwright install chromium")

    print("\nGoogle credentials")
    try:
        from seo_mcp_server.auth.google_oauth import (
            CLIENT_SECRET_ENV, DEFAULT_CLIENT_SECRETS_FILE, app_home,
            auth_manager, _candidates,
        )
        cs = auth_manager.client_secrets_path
        line(cs.exists(), "client_secret.json",
             str(cs) if cs.exists() else f"save it to {app_home() / DEFAULT_CLIENT_SECRETS_FILE}")
        if not cs.exists():
            print("         searched:")
            for p in _candidates(DEFAULT_CLIENT_SECRETS_FILE, CLIENT_SECRET_ENV):
                print(f"           - {p}")

        tok = auth_manager.token_path
        if tok.exists():
            line(True, "token.json (authorized)", str(tok))
        else:
            print(f"  [ -- ] token.json  -> not yet created; "
                  f"authorize on first GSC/GA4 call")
    except Exception as exc:
        line(False, "credential lookup", f"{type(exc).__name__}: {exc}")

    print("\nTools")
    try:
        from seo_mcp_server.server import mcp
        import asyncio
        names = [t.name for t in asyncio.run(mcp.list_tools())]
        line(len(names) > 0, f"{len(names)} registered", ", ".join(names))
    except Exception as exc:
        line(False, "server import", f"{type(exc).__name__}: {exc}")

    print("\n" + "-" * 46)
    print("Add this to your MCP client config:\n")
    # Running from a clone: point at the main.py shim, which puts the repo on
    # sys.path itself. Installed: `-m` works from anywhere on PATH.
    shim = Path(__file__).resolve().parent.parent / "main.py"
    entry = {"command": sys.executable,
             "args": [str(shim)] if shim.exists() else ["-m", "seo_mcp_server"]}
    print(json.dumps({"mcpServers": {"seo": entry}}, indent=2))
    print()
    print("All good - the server is ready." if ok
          else "Some checks failed. Fix the items marked FAIL above.")
    print()
    return 0 if ok else 1


def main():
    """Boots the FastMCP server using the default stdio transport."""
    if "--check" in sys.argv or "--doctor" in sys.argv:
        raise SystemExit(_check())

    from seo_mcp_server.server import mcp
    # FastMCP handles the async event loop and thread pooling.
    mcp.run()


if __name__ == "__main__":
    main()
