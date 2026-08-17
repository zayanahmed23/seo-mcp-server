"""
Google Search Console (GSC) API Wrapper.
Provides async-compatible functions to fetch search analytics and indexing data.
"""

from typing import Dict, Any, List, Optional
from googleapiclient.discovery import build
from src.auth.google_oauth import get_google_credentials

class SearchConsoleClient:
    """Manages interactions with the Google Search Console API."""
    
    def __init__(self) -> None:
        self._service = None

    @property
    def service(self):
        """Lazy-loads the API client using secure OAuth credentials."""
        if not self._service:
            # Retrieves credentials dynamically; no hardcoded keys here.
            creds = get_google_credentials()
            self._service = build("webmasters", "v3", credentials=creds)
        return self._service

    def get_verified_sites(self) -> List[str]:
        """
        Retrieves a list of all verified properties in the user's Search Console account.
        """
        site_list = self.service.sites().list().execute()
        return [site.get("siteUrl") for site in site_list.get("siteEntry", []) if "siteUrl" in site]

    def query_search_analytics(
        self, 
        site_url: str, 
        start_date: str, 
        end_date: str, 
        dimensions: Optional[List[str]] = None,
        row_limit: int = 100
    ) -> Dict[str, Any]:
        """
        Queries the Search Analytics report for clicks, impressions, CTR, and position.
        
        Args:
            site_url: The exact property URL (e.g., 'https://www.example.com/').
            start_date: YYYY-MM-DD format.
            end_date: YYYY-MM-DD format.
            dimensions: List of dimensions to group by (e.g., ['query', 'page', 'device']).
            row_limit: Maximum number of rows to return to protect LLM context limits.
            
        Returns:
            A dictionary containing the parsed rows or error messages.
        """
        if dimensions is None:
            dimensions = ["query", "page"]

        request_body = {
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": dimensions,
            "rowLimit": row_limit
        }

        try:
            response = self.service.searchanalytics().query(
                siteUrl=site_url, body=request_body
            ).execute()
            
            return {
                "site": site_url,
                "rows_returned": len(response.get("rows", [])),
                "data": response.get("rows", [])
            }
        except Exception as e:
            return {"error": f"Failed to query Search Console for {site_url}: {str(e)}"}

# Singleton for use in FastMCP tool routing
gsc_client = SearchConsoleClient()