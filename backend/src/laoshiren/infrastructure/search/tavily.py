from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from laoshiren.application.search.ports import SearchHit, SearchResponse


class TavilyWebSearchAdapter:
    """Tavily search API adapter."""

    def __init__(
        self,
        *,
        api_key: str,
        api_base: str = "https://api.tavily.com",
        timeout_seconds: float = 15.0,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Tavily API key is required.")
        self._api_key = api_key
        self._url = f"{api_base.rstrip('/')}/search"
        self._timeout = timeout_seconds

    async def search(
        self,
        *,
        query: str,
        limit: int,
        recency_days: int | None,
        include_domains: tuple[str, ...] | None,
        exclude_domains: tuple[str, ...] | None,
    ) -> SearchResponse:
        payload: dict[str, Any] = {
            "api_key": self._api_key,
            "query": query,
            "max_results": limit,
            "search_depth": "basic",
            "include_answer": False,
        }
        if include_domains:
            payload["include_domains"] = list(include_domains)
        if exclude_domains:
            payload["exclude_domains"] = list(exclude_domains)
        if recency_days is not None and recency_days > 0:
            payload["days"] = recency_days
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(self._url, json=payload)
        response.raise_for_status()
        body: Any = response.json()
        results = body.get("results", [])
        hits: list[SearchHit] = []
        if isinstance(results, list):
            for index, item in enumerate(results[:limit]):
                if not isinstance(item, dict):
                    continue
                url = str(item.get("url", ""))
                domain = urlparse(url).netloc if url else ""
                score_raw = item.get("score", 0.0)
                try:
                    score = float(score_raw)
                except (TypeError, ValueError):
                    score = max(0.1, 1.0 - (index * 0.1))
                hits.append(
                    SearchHit(
                        title=str(item.get("title", "")),
                        url=url,
                        snippet=str(item.get("content", "")),
                        published_at=None,
                        domain=domain,
                        rank_score=min(1.0, max(0.0, score)),
                    )
                )
        return SearchResponse(
            query=query,
            provider="tavily",
            retrieved_at=datetime.now(UTC),
            hits=tuple(hits),
        )
