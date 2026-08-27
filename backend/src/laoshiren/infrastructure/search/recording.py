from datetime import UTC, datetime

from laoshiren.application.search.ports import SearchHit, SearchResponse


class RecordingWebSearchAdapter:
    """Deterministic search results for development and tests."""

    async def search(
        self,
        *,
        query: str,
        limit: int,
        recency_days: int | None,
        include_domains: tuple[str, ...] | None,
        exclude_domains: tuple[str, ...] | None,
    ) -> SearchResponse:
        del recency_days, exclude_domains
        domain = include_domains[0] if include_domains else "example.com"
        hits = tuple(
            SearchHit(
                title=f"Fixture result {index + 1} for {query}",
                url=f"https://{domain}/article/{index + 1}",
                snippet=f"Fixture snippet about {query} (result {index + 1}).",
                published_at=None,
                domain=domain,
                rank_score=max(0.1, 1.0 - (index * 0.1)),
            )
            for index in range(min(limit, 3))
        )
        return SearchResponse(
            query=query,
            provider="recording",
            retrieved_at=datetime.now(UTC),
            hits=hits,
        )
