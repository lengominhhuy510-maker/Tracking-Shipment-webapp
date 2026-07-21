"""Agent B's single search tool (§6.3c) — domain-facing, no httpx here.

Delegates to the Tavily integration client; missing key or provider failure
degrades to an empty result list so the research loop never crashes on I/O.
"""

import logging

from app.config import settings
from app.integrations import tavily_client
from app.integrations.errors import ExternalIntegrationError
from app.integrations.tavily_client import SearchResult

logger = logging.getLogger(__name__)

__all__ = ["SearchResult", "web_search"]


async def web_search(query: str) -> list[SearchResult]:
    """Tìm tin tức/sự kiện ảnh hưởng tuyến hàng hải. Trả list SearchResult."""
    api_key = settings.SEARCH_API_KEY.strip()
    if not api_key:
        logger.warning("web_search: thiếu SEARCH_API_KEY — trả list rỗng")
        return []
    try:
        return await tavily_client.search(query, api_key=api_key)
    except ExternalIntegrationError as exc:
        logger.warning("web_search failed (%s) — trả list rỗng", exc)
        return []
