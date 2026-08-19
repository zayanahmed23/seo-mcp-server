# SEO MCP Server

An [MCP](https://modelcontextprotocol.io) server exposing SEO tools to LLM
clients (e.g. Claude Desktop, Claude Code):

- `audit_site_structure` — crawls a site with Playwright and returns technical
  SEO metadata (titles, meta descriptions, H1s, canonical URLs, clean text).
- `get_gsc_performance` — queries Google Search Console for organic search
  performance (clicks, impressions, CTR, position).
- `get_ga4_metrics` — queries Google Analytics 4 for traffic, engagement, and
  conversion metrics.

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

`playwright install chromium` downloads the browser binary the crawler tool
needs; it's a separate step from `pip install` and is easy to miss.

### 2. Create a Google OAuth client

`get_gsc_performance` and `get_ga4_metrics` need read-only access to your
Google Search Console and Analytics data via OAuth:

1. In [Google Cloud Console](https://console.cloud.google.com/), create (or
   select) a project and enable the **Search Console API** and **Google
   Analytics Data API**.
2. Under **APIs & Services → Credentials**, create an **OAuth client ID** of
   type **Desktop app**.
3. Download the JSON and save it as `client_secret.json` in this directory
   (`seo-mcp-server/`).

The server requests only the `webmasters.readonly` and `analytics.readonly`
scopes — it cannot modify your GSC/GA4 configuration or data.

### 3. Run the server

```bash
python main.py
```

On first use of `get_gsc_performance` or `get_ga4_metrics`, a browser window
opens for you to sign in and grant access. The resulting credentials are
cached to `token.json` in this directory so you aren't prompted again until
the token is revoked or expires without a valid refresh token.

To use this server from an MCP client, point it at `python main.py` (stdio
transport) in that client's MCP server configuration.

## Security notes

- **`client_secret.json` and `token.json` are gitignored** — never commit
  them. `token.json` in particular contains a long-lived refresh token for
  your GSC/GA4 data and is written with owner-only (`0600`) file permissions
  on Linux/Mac. Windows' filesystem API doesn't expose the same POSIX
  permission model, so on Windows you should rely on your user account/disk
  encryption for protection rather than file mode bits.
- **The crawler only fetches `http`/`https` URLs** and refuses to target
  localhost, private/internal IP ranges (RFC1918), link-local addresses
  (including the `169.254.169.254` cloud metadata endpoint), and other
  reserved ranges — both before starting a crawl and on every individual
  request inside the browser (covering redirects and subresources). This
  matters because `start_url` may ultimately be influenced by content an
  LLM has read elsewhere.
- Each crawl is capped at 20 pages and 3 link-hops deep, and only follows
  links on the same origin under the given `path_prefix`.
- Raw HTML fetched by the crawler is written to `crawl_output/` (gitignored)
  using a hash of the URL as the filename — crawled URLs never get used to
  construct filesystem paths directly.
- Tool errors are logged in full locally but returned to the calling
  LLM/client in a redacted form with local filesystem paths stripped out.

## Project layout

```
main.py                    Entry point; runs the FastMCP server over stdio
src/server.py               Tool definitions (audit_site_structure, get_gsc_performance, get_ga4_metrics)
src/auth/google_oauth.py    Google OAuth credential lifecycle
src/api/gsc.py              Search Console API wrapper
src/api/ga4.py              Analytics Data API wrapper
src/crawler/engine.py       Playwright-based crawler with SSRF guards
```
