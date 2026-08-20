"""
Google OAuth 2.0 Authentication Provider for MCP SEO Server.
Handles multi-scope authorization and token lifecycle management.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import List, Optional
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Minimal read-only scopes required for SEO auditing
SCOPES: List[str] = [
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/analytics.readonly",
]

DEFAULT_CLIENT_SECRETS_FILE = "client_secret.json"
DEFAULT_TOKEN_FILE = "token.json"

# Environment overrides, so an MCP client config can point at credentials
# explicitly via its "env" block.
HOME_ENV = "SEO_MCP_HOME"
CLIENT_SECRET_ENV = "SEO_MCP_CLIENT_SECRET"
TOKEN_ENV = "SEO_MCP_TOKEN"

# The repo directory (…/seo-mcp-server), derived from this file rather than
# from the working directory.
PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent


def app_home() -> Path:
    """Per-user directory holding credentials and cached tokens."""
    override = os.environ.get(HOME_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".seo-mcp"


def _candidates(filename: str, env_var: str) -> List[Path]:
    """
    Locations to search, most explicit first.

    MCP clients spawn the server with an arbitrary working directory, so
    nothing here may be relative to os.getcwd() - that was the cause of
    "missing client_secret.json" for anyone who launched from a client
    rather than from inside the repo.
    """
    override = os.environ.get(env_var)
    found: List[Path] = []
    if override:
        found.append(Path(override).expanduser())
    found.append(app_home() / filename)
    found.append(PACKAGE_ROOT / filename)  # repo-local, for local development
    return found


def _resolve_existing(filename: str, env_var: str) -> Path:
    """First candidate that exists, else the preferred location."""
    options = _candidates(filename, env_var)
    for path in options:
        if path.exists():
            return path
    return options[0]


class GoogleAuthManager:
    """Manages local Google OAuth credentials lifecycle."""

    def __init__(
        self,
        client_secrets_path: Optional[str] = None,
        token_path: Optional[str] = None,
        scopes: Optional[List[str]] = None,
    ) -> None:
        # Paths must never depend on the working directory - see _candidates().
        self.client_secrets_path = (
            Path(client_secrets_path).expanduser()
            if client_secrets_path
            else _resolve_existing(DEFAULT_CLIENT_SECRETS_FILE, CLIENT_SECRET_ENV)
        )
        self.token_path = (
            Path(token_path).expanduser()
            if token_path
            else _resolve_existing(DEFAULT_TOKEN_FILE, TOKEN_ENV)
        )
        self.scopes = scopes or SCOPES

    def get_credentials(self) -> Credentials:
        """
        Retrieves valid user credentials from storage or executes the local OAuth flow.
        
        Returns:
            google.oauth2.credentials.Credentials: Valid authorized credentials.
            
        Raises:
            FileNotFoundError: If client_secret.json is absent during initial authentication.
            RuntimeError: If authentication flow fails.
        """
        creds: Optional[Credentials] = None

        # 1. Load cached token if present
        if self.token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(
                    str(self.token_path), self.scopes
                )
            except Exception:
                # Corrupt cache: reset and re-authenticate
                creds = None

        # 2. Refresh or trigger initial flow if invalid
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception:
                    # Token refresh revoked or failed; fallback to web flow
                    creds = self._run_app_flow()
            else:
                creds = self._run_app_flow()

            # 3. Cache valid credentials
            self._save_token(creds)

        return creds

    def _run_app_flow(self) -> Credentials:
        """Executes local webserver authorization flow."""
        if not self.client_secrets_path.exists():
            searched = "\n  ".join(
                str(p) for p in _candidates(DEFAULT_CLIENT_SECRETS_FILE, CLIENT_SECRET_ENV)
            )
            raise FileNotFoundError(
                "Missing OAuth client secret file. Download your OAuth 2.0 Client ID "
                "(Desktop App) from Google Cloud Console and save it as "
                f"'{app_home() / DEFAULT_CLIENT_SECRETS_FILE}', or set the "
                f"{CLIENT_SECRET_ENV} environment variable.\nSearched:\n  " + searched
            )

        flow = InstalledAppFlow.from_client_secrets_file(
            str(self.client_secrets_path), self.scopes
        )
        return flow.run_local_server(port=0)

    def _save_token(self, creds: Credentials) -> None:
        """
        Caches credentials to token.json with owner-only permissions.

        token.json holds a long-lived refresh token for the user's GSC/GA4
        data, so it's created with 0600 (via the os.open mode, which the
        umask can only narrow, never widen) instead of relying on default
        permissions - which on shared/multi-user systems can leave it
        group- or world-readable.
        """
        # Create the parent directory owner-only before writing a token into it.
        parent = self.token_path.parent
        if not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(parent, stat.S_IRWXU)  # 0700
            except OSError:
                pass  # best-effort; POSIX-only semantics

        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        mode = stat.S_IRUSR | stat.S_IWUSR
        fd = os.open(self.token_path, flags, mode)
        try:
            # os.open's mode only applies when creating a new file; chmod
            # here too in case the file already existed with looser
            # permissions from a previous run.
            os.chmod(self.token_path, mode)
            token_file = os.fdopen(fd, "w", encoding="utf-8")
        except BaseException:
            # fdopen hasn't taken ownership of fd yet, so we must close it.
            os.close(fd)
            raise

        with token_file:
            token_file.write(creds.to_json())


# Singleton accessor for API services
auth_manager = GoogleAuthManager()


def get_google_credentials() -> Credentials:
    """Convenience function for downstream API clients."""
    return auth_manager.get_credentials()