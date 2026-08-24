import httpx
import pytest

from laoshiren.application.memories.context import EmbeddingProviderError
from laoshiren.infrastructure.ai.embeddings import OpenAICompatibleEmbeddingProvider

pytestmark = pytest.mark.asyncio


async def test_openai_compatible_embedding_response_is_validated() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/embeddings"
        assert request.headers["Authorization"] == "Bearer secret"
        return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2, 0.3]}]})

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
        return httpx.Response(200, json={"data": [{"embedding": [0.1]}]})

    provider = OpenAICompatibleEmbeddingProvider(
        api_key="secret",
        model="embedding-model",
        api_base="https://embedding.test/v1",
        dimensions=3,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(EmbeddingProviderError):
        await provider.embed("remember this")
