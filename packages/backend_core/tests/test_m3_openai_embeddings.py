"""M3-02b OpenAI embedding provider tests (ING-18, OPEN-31 D3). No real call: every request goes
to an ``httpx.MockTransport``. Covers batching, retry for 429 and 5xx, terminal 4xx, malformed
answers, and that neither the key nor the text reaches an exception message or a log line."""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from knowserve_core.embeddings import (
    EmbeddingError,
    build_embedding_provider,
)
from knowserve_core.embeddings_openai import OpenAIEmbeddingProvider

pytestmark = pytest.mark.m3

KEY = "sk-test-not-a-real-key-0123456789"
DIMS = 4


def vector(seed: int) -> list[float]:
    return [float(seed), 0.0, 0.0, 1.0]


class Recorder:
    def __init__(self, *statuses: int) -> None:
        self.statuses = list(statuses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status = self.statuses.pop(0) if self.statuses else 200
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "nope"}})
        body = json.loads(request.content)
        # Reply out of order on purpose: the provider sorts by index.
        data = [{"index": i, "embedding": vector(int(t))} for i, t in enumerate(body["input"])]
        return httpx.Response(200, json={"data": list(reversed(data))})


def provider(recorder: Recorder, **kw: object) -> OpenAIEmbeddingProvider:
    async def no_sleep(_: float) -> None:
        return None

    return OpenAIEmbeddingProvider(
        KEY,
        model="text-embedding-3-small",
        dimensions=DIMS,
        transport=httpx.MockTransport(recorder),
        sleep=no_sleep,
        **kw,  # type: ignore[arg-type]
    )


async def test_ing18_batches_and_keeps_order() -> None:
    rec = Recorder()
    out = await provider(rec, batch_size=2).embed(["1", "2", "3", "4", "5"])
    assert [v[0] for v in out] == [1.0, 2.0, 3.0, 4.0, 5.0]
    sizes = [len(json.loads(r.content)["input"]) for r in rec.requests]
    assert sizes == [2, 2, 1]
    first = json.loads(rec.requests[0].content)
    assert first["model"] == "text-embedding-3-small" and first["dimensions"] == DIMS
    assert rec.requests[0].headers["authorization"] == f"Bearer {KEY}"


async def test_ing18_empty_input_makes_no_request() -> None:
    rec = Recorder()
    assert await provider(rec).embed([]) == []
    assert rec.requests == []


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_ing18_retries_rate_limits_and_server_errors(status: int) -> None:
    rec = Recorder(status, status)
    out = await provider(rec, max_attempts=3).embed(["7"])
    assert out == [vector(7)] and len(rec.requests) == 3


async def test_ing18_gives_up_after_the_attempt_budget() -> None:
    rec = Recorder(500, 500, 500, 500)
    with pytest.raises(EmbeddingError, match="500"):
        await provider(rec, max_attempts=3).embed(["1"])
    assert len(rec.requests) == 3


@pytest.mark.parametrize("status", [400, 401, 403, 404])
async def test_ing18_other_client_errors_fail_at_once(status: int) -> None:
    rec = Recorder(status)
    with pytest.raises(EmbeddingError):
        await provider(rec).embed(["1"])
    assert len(rec.requests) == 1


async def test_ing18_credential_rejection_is_logged_as_configuration_without_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    rec = Recorder(401)
    with pytest.raises(EmbeddingError) as excinfo:
        await provider(rec).embed(["secret document text"])
    logged = " ".join(r.getMessage() + str(r.__dict__) for r in caplog.records)
    assert "configuration error" in logged
    for text in (str(excinfo.value), logged):
        assert KEY not in text and "secret document text" not in text


async def test_ing18_timeout_is_retried_then_reported_without_details() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("slow", request=request)

    async def no_sleep(_: float) -> None:
        return None

    p = OpenAIEmbeddingProvider(
        KEY,
        model="m",
        dimensions=DIMS,
        max_attempts=2,
        transport=httpx.MockTransport(handler),
        sleep=no_sleep,
    )
    with pytest.raises(EmbeddingError, match="ReadTimeout"):
        await p.embed(["x"])
    assert calls == 2


@pytest.mark.parametrize(
    "body",
    [
        {"nothing": []},
        {"data": [{"index": 0, "embedding": [1.0]}]},  # wrong width
        {"data": []},  # wrong count
        {"data": [{"index": 0, "embedding": "abc"}]},
    ],
)
async def test_ing18_malformed_answers_are_errors(body: dict) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    p = OpenAIEmbeddingProvider(
        KEY, model="m", dimensions=DIMS, transport=httpx.MockTransport(handler)
    )
    with pytest.raises(EmbeddingError):
        await p.embed(["1"])


def test_ing18_factory_builds_the_openai_provider_and_still_refuses_fake_in_production() -> None:
    built = build_embedding_provider(
        "openai", "production", model="m", dimensions=DIMS, api_key=KEY, batch_size=8
    )
    assert isinstance(built, OpenAIEmbeddingProvider)
    with pytest.raises(RuntimeError, match="not allowed in production"):
        build_embedding_provider("fake", "production", model="m", dimensions=DIMS)
