import httpx
import pytest

from laoshiren.application.ai.ports import EmbeddingProviderError
from laoshiren.infrastructure.ai.embeddings import OpenAICompatibleEmbeddingProvider

pytestmark = pytest.mark.asyncio


async def test_openai_compatible_embedding_response_is_validated() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/embeddings"
        assert request.headers["Authorization"] == "Bearer secret"
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]})

    provider = OpenAICompatibleEmbeddingProvider(
        api_key="secret",
        model="embedding-model",
        api_base="https://embedding.test/v1",
        dimensions=3,
        transport=httpx.MockTransport(handler),
    )

    assert await provider.embed("remember this") == [0.1, 0.2, 0.3]


async def test_invalid_embedding_dimension_is_normalized_to_provider_error() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1]}]})

    provider = OpenAICompatibleEmbeddingProvider(
        api_key="secret",
        model="embedding-model",
        api_base="https://embedding.test/v1",
        dimensions=3,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(EmbeddingProviderError):
        await provider.embed("remember this")


async def test_embedding_batch_is_returned_in_provider_index_order() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert b'"first"' in request.content
        assert b'"second"' in request.content
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0]},
                    {"index": 0, "embedding": [1.0, 0.0]},
                ]
            },
        )

    provider = OpenAICompatibleEmbeddingProvider(
        api_key="secret",
        model="embedding-model",
        api_base="https://embedding.test/v1",
        dimensions=2,
        transport=httpx.MockTransport(handler),
    )

    assert await provider.embed_many(["first", "second"]) == [
        [1.0, 0.0],
        [0.0, 1.0],
    ]
