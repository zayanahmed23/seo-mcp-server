# Security Policy

## Reporting a vulnerability

If you find a security issue in this project, please open a private report
via GitHub's "Report a vulnerability" feature on this repository (Security
tab → Advisories) instead of a public issue, so it can be assessed before
details are public.

## Scope notes

- This server runs locally over the MCP stdio transport and is not designed
  to be exposed as a network service.
- `client_secret.json` and `token.json` hold live Google OAuth credentials.
  They are gitignored by default — never commit them, and treat `token.json`
  as sensitive since it contains a long-lived refresh token scoped to
  read-only Search Console and Analytics access.
- The crawler tool (`audit_site_structure`) validates URLs against
  SSRF targets (localhost, private/link-local/reserved IP ranges) both
  up front and per-request inside the browser context. If you find a way
  to bypass this (e.g. via DNS rebinding, redirect chains, or open
  redirects on an allowed host), please report it.
