from __future__ import annotations

from fastapi.testclient import TestClient

from app import db
from app.config import settings
from app.main import app


def test_bootstrap_returns_startup_data(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", tmp_path / "boot.db")
    db.init_db()
    with TestClient(app) as client:
        client.get("/")
        response = client.get("/api/bootstrap")
        assert response.status_code == 200
        data = response.json()
        assert data["user"]["id"] == "anna"
        assert "tasks" in data and "meetings" in data and "audit" in data


def test_html_is_gzipped(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", tmp_path / "gzip.db")
    db.init_db()
    with TestClient(app) as client:
        client.get("/")
        response = client.get("/", headers={"Accept-Encoding": "gzip"})
        assert response.status_code == 200
        assert response.headers.get("content-encoding") == "gzip"
        assert response.headers.get("content-length")
        assert response.headers.get("transfer-encoding") is None
        assert "Accept-Encoding" in response.headers.get("vary", "")


def test_first_visit_returns_html_without_redirect(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", tmp_path / "first.db")
    db.init_db()
    with TestClient(app) as client:
        response = client.get("/", follow_redirects=False, headers={"Accept-Encoding": "gzip"})
        assert response.status_code == 200
        assert settings.session_cookie in client.cookies
        assert response.headers.get("cache-control") == "no-store"
        assert response.headers.get("content-encoding") == "gzip"
        assert response.headers.get("content-length")
        assert response.headers.get("transfer-encoding") is None


def test_html_without_gzip_has_content_length(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", tmp_path / "plain.db")
    db.init_db()
    with TestClient(app) as client:
        client.get("/")
        response = client.get("/", headers={"Accept-Encoding": "identity"})
        assert response.status_code == 200
        assert "content-encoding" not in response.headers
        assert response.headers.get("content-length")
        assert response.headers.get("transfer-encoding") is None


def test_html_is_brotli(tmp_path, monkeypatch):
    import pytest

    pytest.importorskip("brotli")
    monkeypatch.setattr(settings, "db_path", tmp_path / "br.db")
    db.init_db()
    with TestClient(app) as client:
        client.get("/")
        response = client.get("/", headers={"Accept-Encoding": "br"})
        assert response.status_code == 200
        assert response.headers.get("content-encoding") == "br"
        assert response.headers.get("content-length")
        assert response.headers.get("transfer-encoding") is None
        assert "Accept-Encoding" in response.headers.get("vary", "")
