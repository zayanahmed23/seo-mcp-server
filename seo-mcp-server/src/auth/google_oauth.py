"""
Google OAuth 2.0 Authentication Provider for MCP SEO Server.
Handles multi-scope authorization and token lifecycle management.
"""

from __future__ import annotations

import os
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


class GoogleAuthManager:
    """Manages local Google OAuth credentials lifecycle."""

    def __init__(
        self,
        client_secrets_path: str = DEFAULT_CLIENT_SECRETS_FILE,
        token_path: str = DEFAULT_TOKEN_FILE,
        scopes: Optional[List[str]] = None,
    ) -> None:
        self.client_secrets_path = Path(client_secrets_path)
        self.token_path = Path(token_path)
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
            raise FileNotFoundError(
                f"Missing OAuth client secret file at '{self.client_secrets_path}'. "
                "Download your OAuth 2.0 Client ID (Desktop App) from Google Cloud Console."
            )

        flow = InstalledAppFlow.from_client_secrets_file(
            str(self.client_secrets_path), self.scopes
        )
        return flow.run_local_server(port=0)

    def _save_token(self, creds: Credentials) -> None:
        """Atomically caches credentials to token.json."""
        with open(self.token_path, "w", encoding="utf-8") as token_file:
            token_file.write(creds.to_json())


# Singleton accessor for API services
auth_manager = GoogleAuthManager()


def get_google_credentials() -> Credentials:
    """Convenience function for downstream API clients."""
    return auth_manager.get_credentials()