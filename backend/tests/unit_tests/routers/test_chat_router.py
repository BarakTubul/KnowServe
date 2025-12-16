import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.main import app
from app.services.chat_service import ChatService
from app.utils.auth import get_current_user

client = TestClient(app)

ROUTE = "/chat/chat-stream"


# ============================================================
# AUTH OVERRIDE
# ============================================================

@pytest.fixture(autouse=True)
def override_auth():
    def fake_user():
        return {"id": 1, "email": "test@example.com"}

    app.dependency_overrides[get_current_user] = fake_user
    yield
    app.dependency_overrides.clear()


# ============================================================
# Fake streaming generator fixture
# ============================================================

@pytest.fixture
def fake_stream(monkeypatch):
    async def gen(self, messages, user):
        yield "Hello"
        yield " "
        yield "World"

    monkeypatch.setattr(ChatService, "run_query_stream", gen)


# ============================================================
# 1. Streaming works
# ============================================================

def test_chat_stream_returns_streaming_response(fake_stream):
    response = client.post(ROUTE, json={
        "messages": [{"role": "user", "content": "Hi"}],
        "user": {"id": 1}
    })

    assert response.status_code == 200

    chunks = list(response.iter_text())

    # ✔ Ensure streaming happened (not 1 big chunk)
    assert len(chunks) >= 1, "Expected multiple streamed chunks, got a single chunk."

    # ✔ Ensure chunk correctness
    assert chunks == ["Hello", " ", "World"]
    assert "".join(chunks) == "Hello World"


# ============================================================
# 2. Validation error
# ============================================================

def test_chat_stream_missing_fields():
    response = client.post(ROUTE, json={"messages": "not-a-list"})
    assert response.status_code == 422


# ============================================================
# 3. Ensure correct service call
# ============================================================

@pytest.mark.asyncio
async def test_chat_stream_calls_chat_service():

    async def gen(*args, **kwargs):
        yield "ok"

    with patch("app.routers.chat.chat_service.run_query_stream", gen):
        response = client.post(
            ROUTE,
            json={"messages": [{"role": "user", "content": "Hello"}], "user": {"id": 5}},
        )

        chunks = list(response.iter_text())
        assert chunks == ["ok"]


# ============================================================
# 4. Errors are streamed
# ============================================================

def test_chat_stream_service_error():

    async def err(*args, **kwargs):
        raise RuntimeError("boom")
        yield  # makes it an async generator

    with patch("app.routers.chat.chat_service.run_query_stream", err):
        response = client.post(
            ROUTE,
            json={
                "messages": [{"role": "user", "content": "Hi"}],
                "user": {"id": 1}
            }
        )

        chunks = list(response.iter_text())
        assert chunks[0].startswith("[ERROR]")


# ============================================================
# 5. Empty messages still stream
# ============================================================

def test_chat_stream_empty_messages(fake_stream):
    response = client.post(ROUTE, json={
        "messages": [],
        "user": {"id": 1}
    })

    chunks = list(response.iter_text())

    # ✔ Ensure streaming happened
    assert len(chunks) >= 1

    # ✔ Ensure chunk correctness
    assert chunks == ["Hello", " ", "World"]
    assert "".join(chunks) == "Hello World"


# ============================================================
# 6. Large payload still streams
# ============================================================

def test_chat_stream_large_payload(fake_stream):
    large_text = "Hello" * 5000

    response = client.post(ROUTE, json={
        "messages": [{"role": "user", "content": large_text}],
        "user": {"id": 1}
    })

    chunks = list(response.iter_text())

    # ✔ Ensure streaming happened
    assert len(chunks) >= 1

    # ✔ Ensure chunk correctness
    assert chunks == ["Hello", " ", "World"]
    assert "".join(chunks) == "Hello World"
