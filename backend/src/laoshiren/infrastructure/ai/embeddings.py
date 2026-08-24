from typing import Any

import httpx

from laoshiren.application.memories.context import EmbeddingProviderError


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
        clean_text = text.strip()
        if not clean_text:
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
                        "input": clean_text,
                        "dimensions": self._dimensions,
                        "encoding_format": "float",
                    },
                )
            response.raise_for_status()
            body: Any = response.json()
            vector = body["data"][0]["embedding"]
            if not isinstance(vector, list) or len(vector) != self._dimensions:
                raise ValueError("Embedding response has an invalid vector dimension.")
            return [float(value) for value in vector]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exception:
            raise EmbeddingProviderError("Embedding provider request failed.") from exception
