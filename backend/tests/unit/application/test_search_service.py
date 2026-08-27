from uuid import uuid4

import pytest

from laoshiren.application.search.service import SearchApplicationService
from laoshiren.infrastructure.search.recording import RecordingWebSearchAdapter

pytestmark = pytest.mark.asyncio


async def test_search_official_boosts_configured_domains() -> None:
    service = SearchApplicationService(RecordingWebSearchAdapter())
    payload = await service.search_official(
        user_id=uuid4(),
        query="报名截止",
        official_domains=("developer.huawei.com",),
    )
    assert payload["official_domains"] == ["developer.huawei.com"]
    assert payload["items"]
    assert payload["items"][0]["domain"] == "developer.huawei.com"


async def test_search_web_uses_cache_on_repeat() -> None:
    service = SearchApplicationService(RecordingWebSearchAdapter(), cache_ttl_seconds=3600)
    first = await service.search_web(user_id=uuid4(), query="缓存测试")
    second = await service.search_web(user_id=uuid4(), query="缓存测试")
    assert first["replayed"] is False
    assert second["replayed"] is True
