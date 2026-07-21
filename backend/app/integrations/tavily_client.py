"""Tavily search client (Option 1.5, Decision 0005) — typed result + error mapping.

POST https://api.tavily.com/search with the API key in the JSON body. Provider
dicts never leave this file; every httpx/parse failure maps to
``ExternalIntegrationError`` with a ``retryable`` flag.
"""

import logging

import httpx
from pydantic import BaseModel

from app.integrations.errors import ExternalIntegrationError

logger = logging.getLogger(__name__)

SEARCH_URL = "https://api.tavily.com/search"
_TIMEOUT_S = 20


class SearchResult(BaseModel):
    title: str
    url: str
    content: str
    score: float | None = None


async def search(query: str, *, api_key: str, max_results: int = 5) -> list[SearchResult]:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            resp = await client.post(
                SEARCH_URL,
                json={
                    "api_key": api_key,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "basic",
                },
            )
            resp.raise_for_status()
            payload = resp.json()
    except httpx.HTTPStatusError as exc:
        retryable = exc.response.status_code not in (400, 401, 403, 422)
        raise ExternalIntegrationError(
            f"tavily HTTP {exc.response.status_code}", retryable=retryable
        ) from exc
    except httpx.HTTPError as exc:
        raise ExternalIntegrationError(f"tavily request failed: {exc!r}", retryable=True) from exc

    try:
        return [
            SearchResult(
                title=str(item.get("title", "")),
                url=str(item["url"]),
                content=str(item.get("content", "")),
                score=float(item["score"]) if item.get("score") is not None else None,
            )
            for item in payload["results"]
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise ExternalIntegrationError(f"tavily payload unusable: {exc!r}", retryable=True) from exc
