from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def login(email: str, password: str) -> str:
    r = client.post(
        "/auth/login",
        data={
            "username": email,
            "password": password
        }
    )
    r.raise_for_status()
    return r.json()["access_token"]


def test_chat_system_real_pipeline():
    token = login("alicehr@example.com", "SecurePass123")

    response = client.post(
        "/chat/stream",
        headers={
            "Authorization": f"Bearer {token}"
        },
        json={
            "messages": [
                {
                    "role": "user",
                    "content": "What is the HR vacation policy?"
                }
            ]
        },
        stream=True
    )

    assert response.status_code == 200

    text = ""
    for chunk in response.iter_text():
        text += chunk

    print(text)

    # ✅ loose, semantic assertions
    assert len(text) > 30
    assert "vacation" in text.lower() or "leave" in text.lower()
    assert "error" not in text.lower()
