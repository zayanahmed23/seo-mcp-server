# SEO MCP Server

Give your AI assistant read access to your real SEO data. It crawls your site
for technical issues, and pulls your actual Search Console and Analytics
numbers — so you can ask questions like:

> *"Crawl example.com and list every page missing a meta description."*
>
> *"Which queries lost the most clicks last month vs the month before?"*
>
> *"Cross-reference my top landing pages in GA4 with their GSC positions."*

Works with any [MCP](https://modelcontextprotocol.io) client — Claude Desktop,
Claude Code, Cursor, or your own.

## Tools

| Tool | What it does |
| --- | --- |
| `audit_site_structure` | Crawls a site with a headless browser. Returns titles, meta descriptions, robots directives, canonicals, H1s, word counts, and clean text per page. |
| `list_verified_sites` | Lists the Search Console properties your Google account can access. Start here — GSC needs the exact property string. |
| `get_gsc_performance` | Search Console clicks, impressions, CTR and average position, grouped by query, page, device or country. |
| `get_ga4_metrics` | GA4 sessions, active users, bounce rate, session duration, conversions and revenue. |

Read-only throughout. The OAuth scopes requested (`webmasters.readonly`,
`analytics.readonly`) cannot modify anything in your Google account.

## Quickstart

**1. Install**

```bash
git clone https://github.com/zayanahmed23/seo-mcp-server.git
cd seo-mcp-server/seo-mcp-server
pip install -e .
python -m playwright install chromium
```

`playwright install chromium` downloads the browser the crawler drives. It's a
separate step from `pip install` and easy to miss — run it with the same Python
you'll run the server with.

**2. Get Google credentials**

1. In [Google Cloud Console](https://console.cloud.google.com/), create or pick a project.
2. Enable the **Google Search Console API** and the **Google Analytics Data API**.
3. Under **APIs & Services → Credentials**, create an **OAuth client ID** → type **Desktop app**.
4. Download the JSON and save it as `client_secret.json` in `~/.seo-mcp/`
   (`C:\Users\<you>\.seo-mcp\` on Windows).

**3. Check your setup**

```bash
seo-mcp-server --check      # or: python main.py --check
```

This verifies every dependency, the browser, and your credentials — then prints
the exact config block for your MCP client, with the right interpreter path
already filled in:

```
seo-mcp-server setup check
----------------------------------------------

Runtime
  [OK  ] Python 3.14.4

Dependencies
  [OK  ] mcp (FastMCP)
  [OK  ] playwright
  ...

Browser
  [OK  ] Chromium for Playwright

Google credentials
  [OK  ] client_secret.json  -> C:\Users\you\.seo-mcp\client_secret.json
  [ -- ] token.json  -> not yet created; authorize on first GSC/GA4 call

Tools
  [OK  ] 4 registered  -> audit_site_structure, list_verified_sites, ...
```

**4. Add it to your MCP client**

Paste what `--check` printed. It looks like this:

```json
{
  "mcpServers": {
    "seo": {
      "command": "/path/to/python",
      "args": ["/path/to/seo-mcp-server/main.py"]
    }
  }
}
```

For Claude Desktop that goes in `claude_desktop_config.json`; for Claude Code,
`.mcp.json` or `claude mcp add`. Restart the client afterwards.

**5. Authorize**

The first GSC or GA4 call opens a browser to sign in to Google. Credentials are
cached to `~/.seo-mcp/token.json` so it only happens once.

The crawler needs no authorization at all — you can start auditing sites
immediately, before touching any of the Google setup.

## Configuration

Set these in your MCP client's `env` block if you keep credentials elsewhere:

| Variable | Default | Purpose |
| --- | --- | --- |
| `SEO_MCP_HOME` | `~/.seo-mcp` | Directory for credentials and cached tokens |
| `SEO_MCP_CLIENT_SECRET` | `$SEO_MCP_HOME/client_secret.json` | OAuth client secret path |
| `SEO_MCP_TOKEN` | `$SEO_MCP_HOME/token.json` | Cached token path |

## Date ranges

Both Google tools accept the same flexible dates, normalized to the `YYYY-MM-DD`
the APIs require:

| Input | Meaning |
| --- | --- |
| `2026-03-14` | that exact day |
| `2026-03` | a whole month |
| `today`, `yesterday` | relative to now |
| `30daysAgo`, `30 days ago` | N days back |
| `last7days`, `past 30 days` | a window ending today |
| `thisMonth`, `lastMonth` | calendar month |
| `thisYear`, `lastYear` | calendar year |

Period tokens are role-aware: as an `end_date` they resolve to the period's
**last** day, so `start_date="lastMonth", end_date="lastMonth"` covers the whole
month. Invalid dates are rejected before any network or OAuth work, and the
response echoes the resolved range plus notes — a future end date clamped to
today, or a start date beyond Search Console's ~16-month retention.

## Crawler behaviour

- **Honours `robots.txt`.** Disallowed URLs are skipped and reported in
  `blocked_urls`. Pass `respect_robots=false` only for a site you own.
- **Capped** at 20 pages, 3 link-hops, and a 45-second budget. Hitting a limit
  returns partial results with `stopped_early` set rather than failing — MCP
  clients typically abort a tool call around 60s.
- **Same-origin only**, restricted to `path_prefix`.
- **Blocks internal targets.** Only `http`/`https`, and never localhost,
  private/RFC1918 ranges, link-local addresses (including the
  `169.254.169.254` cloud metadata endpoint), or other reserved ranges —
  checked before the crawl and again on every request inside the browser, so
  redirects and subresources are covered too.
- Raw HTML is written to `crawl_output/` (gitignored), named by a hash of the
  URL so crawled URLs never build filesystem paths.

## Security

- `client_secret.json` and `token.json` are gitignored and live outside the
  repo by default. `token.json` holds a long-lived refresh token and is written
  `0600` inside a `0700` directory on Linux/macOS. Windows doesn't use POSIX
  permission bits, so rely on your account and disk encryption there.
- Tool errors are logged in full locally but redacted before crossing the MCP
  boundary — local filesystem paths are stripped, since responses may be
  relayed to a hosted model.
- Found a vulnerability? See [SECURITY.md](../SECURITY.md).

## Development

```bash
pip install -e ".[dev]"
pytest                  # fast, offline
pytest -m network       # also hit the network
```

The suite is hermetic — it never reads your real credentials, touches the
network, or writes into the repo. Tests that need outbound access are marked
`network` and deselected by default.

Three equivalent ways to run the server: `seo-mcp-server`,
`python -m seo_mcp_server`, or `python main.py` straight from a clone.

## Current limits

Honest about what this doesn't do yet:

- **On-page only.** No backlink, competitor or SERP data — that needs a paid
  provider, and Search Console reports your own performance, not your link graph.
- **The crawl is metadata-level.** No sitemap parsing, structured data,
  hreflang, image alt coverage, redirect chains, or Core Web Vitals yet.
- **Single user, local.** OAuth assumes one person on one machine over stdio.
- **GA4 metrics are a fixed set** and can't be chosen per-query.

Issues and PRs welcome.

## Licence

AGPL-3.0 — see [LICENSE](../LICENSE).
