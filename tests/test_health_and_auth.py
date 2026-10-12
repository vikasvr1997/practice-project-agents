from fastapi.testclient import TestClient

from app.main import app


def test_health_needs_no_key():
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}


def test_chat_rejects_missing_key():
    with TestClient(app) as client:
        response = client.post("/chat", json={"user_id": "u1", "message": "hi"})
        assert response.status_code == 401


def test_chat_rejects_wrong_key():
    with TestClient(app) as client:
        response = client.post(
            "/chat", json={"user_id": "u1", "message": "hi"}, headers={"X-API-Key": "nope"}
        )
        assert response.status_code == 401


def test_bad_user_id_is_rejected():
    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={"user_id": "../../etc", "message": "hi"},
            headers={"X-API-Key": "test-key"},
        )
        assert response.status_code == 422
