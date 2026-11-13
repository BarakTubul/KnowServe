"""OpenAI embedding provider (ING-18, OPEN-31 D3), written for M3-02b.

Calls ``POST /v1/embeddings`` directly with ``httpx`` (no SDK). Texts go out in batches of
``batch_size`` (Settings ``KS_EMBEDDING_BATCH_SIZE``); each request has a bounded timeout
(``KS_EMBEDDING_TIMEOUT_SECONDS``). A request is retried a few times for rate limits (429), server
errors (5xx), timeouts and connection errors, with a short exponential backoff. Anything else
(400, 401, 403, a malformed answer) fails at once. The call is all or nothing: one failed batch
raises ``EmbeddingError`` and no partial result is returned.

Errors and logs never contain the API key, the request body (document text) or the response body.
A 401 or 403 is logged at error level as a configuration problem (the alert in MON-06 reads it).
No test makes a real call: they inject an ``httpx.MockTransport``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence

import httpx

from .embeddings import EmbeddingError

logger = logging.getLogger("knowserve.embeddings")

OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class OpenAIEmbeddingProvider:
    def __init__(
        self,
        api_key: str,
        *,
        model: str,
        dimensions: int,
        batch_size: int = 64,
        timeout_seconds: float = 30.0,
        max_attempts: int = 3,
        backoff_seconds: float = 0.5,
        url: str = OPENAI_EMBEDDINGS_URL,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if batch_size < 1 or max_attempts < 1:
            raise ValueError("batch_size and max_attempts must be at least 1")
        self.model = model
        self.dimensions = dimensions
        self._api_key = api_key
        self._batch_size = batch_size
        self._timeout = timeout_seconds
        self._max_attempts = max_attempts
        self._backoff = backoff_seconds
        self._url = url
        self._transport = transport
        self._sleep = sleep

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        if not texts:
            return vectors
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            for start in range(0, len(texts), self._batch_size):
                batch = list(texts[start : start + self._batch_size])
                vectors.extend(await self._embed_batch(client, batch))
        return vectors

    async def _embed_batch(self, client: httpx.AsyncClient, batch: list[str]) -> list[list[float]]:
        payload = {
            "model": self.model,
            "input": batch,
            "dimensions": self.dimensions,
            "encoding_format": "float",
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = await client.post(self._url, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                # Timeouts and connection errors; the exception text is not logged (it may
                # include the URL, never the key or the body).
                if attempt == self._max_attempts:
                    raise EmbeddingError(
                        f"embedding request failed: {type(exc).__name__}"
                    ) from None
                await self._sleep(self._backoff * 2 ** (attempt - 1))
                continue
            if response.status_code in RETRYABLE_STATUS:
                if attempt == self._max_attempts:
                    raise EmbeddingError(f"embedding provider answered {response.status_code}")
                await self._sleep(self._delay(response, attempt))
                continue
            if response.status_code in (401, 403):
                logger.error(
                    "embedding provider rejected the credentials: configuration error",
                    extra={"status": response.status_code},
                )
                raise EmbeddingError(f"embedding provider answered {response.status_code}")
            if response.status_code != 200:
                raise EmbeddingError(f"embedding provider answered {response.status_code}")
            return self._parse(response, len(batch))
        raise EmbeddingError("embedding request failed")  # pragma: no cover - loop always returns

    def _delay(self, response: httpx.Response, attempt: int) -> float:
        base = self._backoff * 2 ** (attempt - 1)
        retry_after = response.headers.get("retry-after")
        if retry_after:
            try:
                return min(max(float(retry_after), base), 30.0)
            except ValueError:
                pass
        return base

    def _parse(self, response: httpx.Response, expected: int) -> list[list[float]]:
        try:
            data = response.json()["data"]
            ordered = sorted(data, key=lambda item: item["index"])
            vectors = [[float(x) for x in item["embedding"]] for item in ordered]
        except (ValueError, KeyError, TypeError):
            raise EmbeddingError("embedding provider sent an unreadable answer") from None
        if len(vectors) != expected or any(len(v) != self.dimensions for v in vectors):
            raise EmbeddingError("embedding provider sent an unexpected number or width")
        return vectors
