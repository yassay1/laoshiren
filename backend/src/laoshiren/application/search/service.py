import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from laoshiren.application.search.ports import SearchHit, SearchResponse, WebSearchPort

_OFFICIAL_BOOST = 0.3


def _normalize_domain(value: str) -> str:
    cleaned = value.strip().lower()
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        cleaned = urlparse(cleaned).netloc
    return cleaned.removeprefix("www.")


def _normalize_domains(domains: tuple[str, ...] | None) -> tuple[str, ...]:
    if not domains:
        return ()
    return tuple(sorted({_normalize_domain(item) for item in domains if item.strip()}))


def _search_cache_key(
    *,
    mode: str,
    query: str,
    limit: int,
    recency_days: int | None,
    domains: tuple[str, ...],
) -> str:
    payload = {
        "mode": mode,
        "query": query.strip().lower(),
        "limit": limit,
        "recency_days": recency_days,
        "domains": list(domains),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return digest


def _boost_official_hits(
    hits: tuple[SearchHit, ...], official_domains: tuple[str, ...]
) -> tuple[SearchHit, ...]:
    if not official_domains:
        return hits
    boosted: list[SearchHit] = []
    for hit in hits:
        domain = _normalize_domain(hit.domain)
        score = hit.rank_score
        if domain in official_domains:
            score = min(1.0, score + _OFFICIAL_BOOST)
        boosted.append(
            SearchHit(
                title=hit.title,
                url=hit.url,
                snippet=hit.snippet,
                published_at=hit.published_at,
                domain=hit.domain,
                rank_score=score,
            )
        )
    return tuple(sorted(boosted, key=lambda item: item.rank_score, reverse=True))


def _trim_snippets(hits: tuple[SearchHit, ...], max_characters: int) -> tuple[SearchHit, ...]:
    total = 0
    trimmed: list[SearchHit] = []
    for hit in hits:
        snippet = hit.snippet
        if total + len(snippet) > max_characters:
            remaining = max_characters - total
            if remaining <= 0:
                break
            snippet = snippet[:remaining]
        total += len(snippet)
        trimmed.append(
            SearchHit(
                title=hit.title,
                url=hit.url,
                snippet=snippet,
                published_at=hit.published_at,
                domain=hit.domain,
                rank_score=hit.rank_score,
            )
        )
    return tuple(trimmed)


class SearchApplicationService:
    def __init__(
        self,
        port: WebSearchPort,
        *,
        default_limit: int = 5,
        max_snippet_characters: int = 8_000,
        cache_ttl_seconds: int = 21_600,
    ) -> None:
        self._port = port
        self._default_limit = default_limit
        self._max_snippet_characters = max_snippet_characters
        self._cache_ttl_seconds = cache_ttl_seconds
        self._cache: dict[str, tuple[datetime, SearchResponse]] = {}

    async def search_web(
        self,
        *,
        user_id: UUID,
        query: str,
        limit: int | None = None,
        recency_days: int | None = None,
        domains: tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        del user_id
        resolved_limit = limit or self._default_limit
        normalized_domains = _normalize_domains(domains)
        cache_key = _search_cache_key(
            mode="web",
            query=query,
            limit=resolved_limit,
            recency_days=recency_days,
            domains=normalized_domains,
        )
        cached = self._read_cache(cache_key)
        if cached is not None:
            return self._to_payload(cached, replayed=True)
        response = await self._port.search(
            query=query,
            limit=resolved_limit,
            recency_days=recency_days,
            include_domains=normalized_domains or None,
            exclude_domains=None,
        )
        hits = _trim_snippets(response.hits, self._max_snippet_characters)
        stored = SearchResponse(
            query=response.query,
            provider=response.provider,
            retrieved_at=response.retrieved_at,
            hits=hits,
            cache_key=cache_key,
        )
        self._write_cache(cache_key, stored)
        return self._to_payload(stored, replayed=False)

    async def search_official(
        self,
        *,
        user_id: UUID,
        query: str,
        official_domains: tuple[str, ...] | None = None,
        limit: int | None = None,
        recency_days: int | None = None,
    ) -> dict[str, Any]:
        del user_id
        resolved_limit = limit or self._default_limit
        domains = _normalize_domains(official_domains)
        cache_key = _search_cache_key(
            mode="official",
            query=query,
            limit=resolved_limit,
            recency_days=recency_days,
            domains=domains,
        )
        cached = self._read_cache(cache_key)
        if cached is not None:
            return self._to_payload(cached, replayed=True, official_domains=domains)
        response = await self._port.search(
            query=query,
            limit=resolved_limit,
            recency_days=recency_days,
            include_domains=domains or None,
            exclude_domains=None,
        )
        hits = _boost_official_hits(response.hits, domains)
        hits = _trim_snippets(hits, self._max_snippet_characters)
        stored = SearchResponse(
            query=response.query,
            provider=response.provider,
            retrieved_at=response.retrieved_at,
            hits=hits,
            cache_key=cache_key,
        )
        self._write_cache(cache_key, stored)
        return self._to_payload(stored, replayed=False, official_domains=domains)

    async def inspect_url(
        self,
        *,
        user_id: UUID,
        url: str,
    ) -> dict[str, Any]:
        del user_id
        normalized = url.strip()
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        cache_key = _search_cache_key(
            mode="url_inspect",
            query=normalized,
            limit=1,
            recency_days=None,
            domains=(),
        )
        cached = self._read_cache(cache_key)
        if cached is not None:
            payload = self._to_payload(cached, replayed=True)
            payload["url"] = normalized
            return payload
        response = await self._port.search(
            query=normalized,
            limit=1,
            recency_days=None,
            include_domains=None,
            exclude_domains=None,
        )
        matching = tuple(
            hit for hit in response.hits if hit.url.rstrip("/") == normalized.rstrip("/")
        )
        hits = matching or response.hits[:1]
        hits = _trim_snippets(hits, self._max_snippet_characters)
        stored = SearchResponse(
            query=normalized,
            provider=response.provider,
            retrieved_at=response.retrieved_at,
            hits=hits,
            cache_key=cache_key,
        )
        self._write_cache(cache_key, stored)
        payload = self._to_payload(stored, replayed=False)
        payload["url"] = normalized
        return payload

    def _read_cache(self, cache_key: str) -> SearchResponse | None:
        entry = self._cache.get(cache_key)
        if entry is None:
            return None
        stored_at, response = entry
        age = (datetime.now(UTC) - stored_at).total_seconds()
        if age > self._cache_ttl_seconds:
            self._cache.pop(cache_key, None)
            return None
        return response

    def _write_cache(self, cache_key: str, response: SearchResponse) -> None:
        self._cache[cache_key] = (datetime.now(UTC), response)

    @staticmethod
    def _to_payload(
        response: SearchResponse,
        *,
        replayed: bool,
        official_domains: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        return {
            "query": response.query,
            "retrieved_at": response.retrieved_at.isoformat(),
            "provider": response.provider,
            "official_domains": list(official_domains),
            "replayed": replayed,
            "items": [
                {
                    "title": hit.title,
                    "url": hit.url,
                    "snippet": hit.snippet,
                    "domain": hit.domain,
                    "published_at": (
                        hit.published_at.isoformat() if hit.published_at is not None else None
                    ),
                    "rank_score": hit.rank_score,
                }
                for hit in response.hits
            ],
        }


def extract_urls_from_search_payload(data: dict[str, Any]) -> set[str]:
    urls: set[str] = set()
    items = data.get("items")
    if not isinstance(items, list):
        return urls
    for item in items:
        if isinstance(item, dict):
            url = item.get("url")
            if isinstance(url, str) and url.strip():
                urls.add(url.strip())
    return urls


def normalize_search_query(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())
