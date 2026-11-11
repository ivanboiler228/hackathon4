from fastapi.testclient import TestClient

from app import db
from app.config import settings
from app.main import app


def _login(client: TestClient, user_id: str) -> None:
    code = db.create_qr_token(user_id, ttl_seconds=60)
    r = client.get(f"/auth/qr?code={code}", follow_redirects=False)
    assert r.status_code == 303
    assert settings.session_cookie in client.cookies


def test_qr_login_and_employee_denied(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", tmp_path / "test.db")
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    db.init_db()

    with TestClient(app) as client:
        _login(client, "igor")
        me = client.get("/api/me").json()
        assert me["role"] == "employee"
        assert "prod" in me["acls"]

        denied = client.post("/api/assistant/ask", json={"q": "Что в D-12?"})
        assert denied.status_code == 403
        assert "закрыт" in denied.json()["detail"]


def test_pii_masking_in_api(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", tmp_path / "test2.db")
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    db.init_db()

    with TestClient(app) as client:
        _login(client, "anna")
        r = client.post(
            "/api/assistant/ask",
            json={"q": "Позвони Ивану Иванову на +375291112233 по вопросу доставки, что говорит регламент?"},
        )
        assert r.status_code == 200
        data = r.json()
        assert "⟦PHONE_1⟧" in data["masked_preview"]
        assert "+375291112233" not in data["masked_preview"]
        assert data["pii_found"].get("PHONE", 0) >= 1
        assert data["sources"]

        audit = client.get("/api/audit").json()
        assert audit["items"]
        assert any(item["action"] == "assistant.ask" for item in audit["items"])


def test_director_can_switch_to_employee_and_back(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", tmp_path / "test3.db")
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    db.init_db()

    with TestClient(app) as client:
        _login(client, "anna")
        assert client.get("/api/me").json()["role"] == "boss"

        switched = client.post("/api/switch-role", json={"user_id": "igor"})
        assert switched.status_code == 200
        me = client.get("/api/me").json()
        assert me["role"] == "employee"
        assert me["is_impersonating"] is True
        assert me["can_switch"] is True

        denied = client.post("/api/assistant/ask", json={"q": "Что в D-12?"})
        assert denied.status_code == 403

        back = client.post("/api/switch-role", json={"user_id": None})
        assert back.status_code == 200
        me = client.get("/api/me").json()
        assert me["role"] == "boss"
        assert me["is_impersonating"] is False
