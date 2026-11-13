"""Embedding provider interface (ING-17, ING-18, OPEN-31 D3) and a deterministic fake.

M3-01 fixes the interface and the fake. The OpenAI implementation (batching, timeouts, retries for
429 and 5xx) is in ``embeddings_openai.py`` behind ``build_embedding_provider``. The fake is
refused in production, like the fake object store.
"""

from __future__ import annotations

import hashlib
import math
import struct
from collections.abc import Sequence
from typing import Literal, Protocol

from .ingestion_contract import EMBEDDING_DIMENSIONS


class EmbeddingError(Exception):
    """The provider failed (network, rate limit, 5xx, bad key). The Worker maps it to
    ``EMBEDDING_FAILED``. The message never contains the API key or the text being embedded."""


class EmbeddingProvider(Protocol):
    model: str
    dimensions: int

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """One vector of ``dimensions`` floats per text, in order. All or nothing: it raises
        ``EmbeddingError`` and returns no partial result."""
        ...


class FakeEmbeddingProvider:
    """Deterministic vectors derived from SHA-256 of the text. Same text, same vector; different
    texts give different, unit-length vectors. Makes no network call. Tests only.

    ``fail_after`` makes the call number ``fail_after`` (counting from 1) raise
    ``EmbeddingError``, so tests can cover a provider failure in the middle of a document.
    """

    model = "fake-embedding"

    def __init__(self, dimensions: int = EMBEDDING_DIMENSIONS, fail_after: int | None = None):
        self.dimensions = dimensions
        self.calls = 0
        self._fail_after = fail_after

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += 1
        if self._fail_after is not None and self.calls >= self._fail_after:
            raise EmbeddingError("fake embedding failure")
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        values: list[float] = []
        counter = 0
        while len(values) < self.dimensions:
            digest = hashlib.sha256(f"{counter}:{text}".encode()).digest()
            # Eight 4-byte unsigned integers per digest, mapped to [-1, 1).
            values.extend((n / 2**31) - 1.0 for n in struct.unpack(">8I", digest))
            counter += 1
        values = values[: self.dimensions]
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return [v / norm for v in values]


def build_embedding_provider(
    kind: Literal["openai", "fake"],
    env: str,
    *,
    model: str,
    dimensions: int,
    api_key: str | None = None,
    batch_size: int = 64,
    timeout_seconds: float = 30.0,
) -> EmbeddingProvider:
    """Choose the provider. The fake is refused in production (KS_ENV=production)."""
    if kind == "fake":
        if env == "production":
            raise RuntimeError("the fake embedding provider is not allowed in production")
        return FakeEmbeddingProvider(dimensions)
    if not api_key:
        raise RuntimeError("KS_OPENAI_API_KEY is required for the openai embedding provider")
    from .embeddings_openai import OpenAIEmbeddingProvider

    return OpenAIEmbeddingProvider(
        api_key,
        model=model,
        dimensions=dimensions,
        batch_size=batch_size,
        timeout_seconds=timeout_seconds,
    )
