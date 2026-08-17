"""
Google Analytics 4 (GA4) API Wrapper.
Fetches traffic, engagement, and e-commerce metrics while enforcing LLM context limits.
"""

from typing import Dict, Any, List, Optional
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    RunReportRequest,
)
from src.auth.google_oauth import get_google_credentials

class AnalyticsClient:
    """Manages interactions with the Google Analytics 4 (GA4) Data API."""
    
    def __init__(self) -> None:
        self._client: Optional[BetaAnalyticsDataClient] = None

    @property
    def client(self) -> BetaAnalyticsDataClient:
        """
        Lazy-loads the GA4 API client using the secure local credentials cache.
        Prevents server crashes on startup if credentials are not yet configured.
        """
        if not self._client:
            # We strictly pull from the auth module; no hardcoded keys.
            creds = get_google_credentials()
            self._client = BetaAnalyticsDataClient(credentials=creds)
        return self._client

    def query_performance_data(
        self, 
        property_id: str, 
        start_date: str, 
        end_date: str, 
        dimensions: Optional[List[str]] = None,
        row_limit: int = 25
    ) -> Dict[str, Any]:
        """
        Queries GA4 for standard traffic, engagement, and e-commerce metrics.
        
        Args:
            property_id: The GA4 Property ID (e.g., '123456789').
            start_date: Start date in YYYY-MM-DD format, or relative like '30daysAgo'.
            end_date: End date in YYYY-MM-DD format, or 'today'.
            dimensions: List of dimensions to group by (defaults to ['sessionDefaultChannelGroup']).
            row_limit: Maximum number of rows to return to protect LLM context limits.
            
        Returns:
            A clean dictionary containing the parsed rows or an error message.
        """
        if dimensions is None:
            dimensions = ["sessionDefaultChannelGroup"]

        # Mix of standard and e-commerce metrics to support all business types
        metric_names = [
            "sessions",               # Standard Traffic
            "activeUsers",            # Standard Traffic
            "bounceRate",             # Engagement
            "averageSessionDuration", # Engagement
            "conversions",            # E-commerce / Lead Gen
            "totalRevenue"            # E-commerce (Returns 0 on non-monetized sites)
        ]

        request = RunReportRequest(
            property=f"properties/{property_id}",
            dimensions=[Dimension(name=d) for d in dimensions],
            metrics=[Metric(name=m) for m in metric_names],
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            limit=row_limit # Enforces strict response truncation at the API level
        )

        try:
            response = self.client.run_report(request=request)
            
            # Parse the gRPC response into a clean, context-friendly Python dictionary
            parsed_rows = []
            for row in response.rows:
                row_data = {}
                for i, dimension_value in enumerate(row.dimension_values):
                    row_data[dimensions[i]] = dimension_value.value
                for i, metric_value in enumerate(row.metric_values):
                    row_data[metric_names[i]] = metric_value.value
                parsed_rows.append(row_data)

            return {
                "property_id": property_id,
                "rows_returned": len(parsed_rows),
                "data": parsed_rows
            }
            
        except Exception as e:
            return {"error": f"Failed to query GA4 for Property {property_id}: {str(e)}"}

# Singleton instance for FastMCP routing
ga4_client = AnalyticsClient()