from typing import Any

import httpx

from laoshiren.application.ai.ports import EmbeddingProviderError


class OpenAICompatibleEmbeddingProvider:
    """Thin HTTP adapter for OpenAI-compatible embedding endpoints."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        api_base: str,
        dimensions: int = 1536,
        timeout_seconds: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key.strip() or not model.strip() or not api_base.strip():
            raise ValueError("Embedding API key, model and base URL are required.")
        if dimensions <= 0 or timeout_seconds <= 0:
            raise ValueError("Embedding dimensions and timeout must be positive.")
        self._api_key = api_key
        self._model = model
        self._url = f"{api_base.rstrip('/')}/embeddings"
        self._dimensions = dimensions
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    async def embed(self, text: str) -> list[float]:
        return (await self.embed_many([text]))[0]

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        clean_texts = [text.strip() for text in texts]
        if not clean_texts or any(not text for text in clean_texts):
            raise ValueError("Embedding input cannot be empty.")
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds, transport=self._transport
            ) as client:
                response = await client.post(
                    self._url,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "model": self._model,
                        "input": clean_texts,
                        "dimensions": self._dimensions,
                        "encoding_format": "float",
                    },
                )
            response.raise_for_status()
            body: Any = response.json()
            data = body["data"]
            if not isinstance(data, list) or len(data) != len(clean_texts):
                raise ValueError("Embedding response has an invalid item count.")
            ordered = sorted(data, key=lambda item: int(item.get("index", 0)))
            vectors: list[list[float]] = []
            for item in ordered:
                vector = item["embedding"]
                if not isinstance(vector, list) or len(vector) != self._dimensions:
                    raise ValueError("Embedding response has an invalid vector dimension.")
                vectors.append([float(value) for value in vector])
            return vectors
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exception:
            raise EmbeddingProviderError("Embedding provider request failed.") from exception
