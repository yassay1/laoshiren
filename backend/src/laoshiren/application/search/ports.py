from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SearchHit:
    title: str
    url: str
    snippet: str
    published_at: datetime | None
    domain: str
    rank_score: float


@dataclass(frozen=True, slots=True)
class SearchResponse:
    query: str
    provider: str
    retrieved_at: datetime
    hits: tuple[SearchHit, ...]
    cache_key: str | None = None


class WebSearchPort(Protocol):
    async def search(
        self,
        *,
        query: str,
        limit: int,
        recency_days: int | None,
        include_domains: tuple[str, ...] | None,
        exclude_domains: tuple[str, ...] | None,
    ) -> SearchResponse: ...
